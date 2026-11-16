"""Statistiche e dati per i grafici.

Le registrazioni del periodo vengono lette una volta (rispettando visibilità e filtri)
e aggregate in Python: per i volumi di una famiglia è veloce anche su Raspberry Pi
e permette di raggruppare per giorno/settimana/mese nel fuso orario locale.

Misure ("measure") disponibili, sempre omogenee:
- "count"     numero di registrazioni (+1)
- "quantity"  somma delle quantità: solo con una singola attività selezionata
- "g:<kind>|<unit>|<agg>"  indicatori con stesso significato, unità e aggregazione
               (es. distanza in km sommata, frequenza cardiaca in media)
- "m:<id>"    un singolo indicatore di un'attività
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from app.extensions import db
from app.models import KIND_LABELS, Activity, ActivityEntry, Category, MetricDefinition
from app.services import entry_service
from app.services.entry_service import EntryFilters
from app.services.period import (
    MONTHS_SHORT_IT,
    Period,
    bucket_key,
    bucket_labels,
    buckets_for,
    local_date_range_utc,
)
from app.utils.formatting import fmt_hours, fmt_number
from app.utils.timezone import local_today, to_local

# Palette categoriale (validata per daltonismo) per serie senza un colore proprio
# (es. periodo attuale vs precedente). Categorie e persone usano il colore scelto dall'utente.
SERIES_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
AGG_LABELS = {"sum": "totale", "avg": "media", "max": "massimo", "min": "minimo"}


# --------------------------------------------------------------------------- filtri
@dataclass
class StatsFilters:
    period: Period
    profile_id: int | None = None
    category_id: int | None = None
    activity_id: int | None = None
    scope: str | None = None
    measure: str = "count"


def load_entries(actor, period: Period, filters: StatsFilters, profile_id: int | None = None) -> list[ActivityEntry]:
    start, end = period.utc_range
    query = entry_service.filtered_query(actor, EntryFilters(
        profile_id=profile_id if profile_id is not None else filters.profile_id,
        category_id=filters.category_id,
        activity_id=filters.activity_id,
        scope=filters.scope,
        date_from=start,
        date_to=end,
    ))
    return list(db.session.scalars(query))


# --------------------------------------------------------------------------- misure
@dataclass
class Measure:
    key: str
    label: str
    unit: str = ""
    aggregation: str = "sum"
    is_duration: bool = False
    metric_ids: set[int] = field(default_factory=set)


def available_measures(family_id: int, activity_id: int | None = None) -> list[Measure]:
    measures = [Measure("count", "Registrazioni (+1)", "")]
    query = db.select(MetricDefinition).join(Activity).where(
        Activity.family_id == family_id, MetricDefinition.data_type.in_(("integer", "decimal", "duration"))
    )
    if activity_id:
        activity = db.session.get(Activity, activity_id)
        if activity and activity.family_id == family_id:
            measures.append(Measure("quantity", f"Quantità ({activity.count_label})", activity.count_label))
        query = query.where(MetricDefinition.activity_id == activity_id)
    metrics = list(db.session.scalars(query.order_by(MetricDefinition.sort_order, MetricDefinition.id)))
    groups: dict[str, Measure] = {}
    for m in metrics:
        unit = "h" if m.data_type == "duration" else (m.unit or "")
        if activity_id:
            key = f"m:{m.id}"
            label = f"{m.name}{' (' + unit + ')' if unit else ''} · {AGG_LABELS[m.aggregation]}"
            groups[key] = Measure(key, label, unit, m.aggregation, m.data_type == "duration", {m.id})
        else:
            key = f"g:{m.kind}|{unit}|{m.aggregation}"
            if key not in groups:
                name = KIND_LABELS.get(m.kind, m.kind) if m.kind != "other" else m.name
                label = f"{name}{' (' + unit + ')' if unit else ''} · {AGG_LABELS[m.aggregation]}"
                groups[key] = Measure(key, label, unit, m.aggregation, m.data_type == "duration")
            groups[key].metric_ids.add(m.id)
    return measures + list(groups.values())


def resolve_measure(measures: list[Measure], key: str) -> Measure:
    for m in measures:
        if m.key == key:
            return m
    return measures[0]


def _values(entries, measure: Measure) -> list[float]:
    if measure.key == "count":
        return [1.0 for _ in entries]
    if measure.key == "quantity":
        return [float(e.quantity) for e in entries]
    values = []
    for e in entries:
        for v in e.metric_values:
            if v.metric_definition_id in measure.metric_ids and v.value_numeric is not None:
                number = float(v.value_numeric)
                values.append(number / 3600 if measure.is_duration else number)
    return values


def aggregate(entries, measure: Measure) -> float | None:
    values = _values(entries, measure)
    if not values:
        return 0.0 if measure.aggregation == "sum" else None
    if measure.aggregation == "sum":
        return sum(values)
    if measure.aggregation == "avg":
        return sum(values) / len(values)
    if measure.aggregation == "max":
        return max(values)
    return min(values)


def fmt_measure(value, measure: Measure) -> str:
    if value is None:
        return "—"
    if measure.is_duration:
        return fmt_hours(value * 3600)
    return f"{fmt_number(value, 1)}{' ' + measure.unit if measure.unit else ''}"


def duration_seconds(entries) -> float:
    """Tempo dedicato: somma degli indicatori di tipo durata (aggregazione somma)."""
    total = 0.0
    for e in entries:
        for v in e.metric_values:
            d = v.definition
            if d.data_type == "duration" and d.aggregation == "sum" and v.value_numeric is not None:
                total += float(v.value_numeric)
    return total


# --------------------------------------------------------------------------- raggruppamenti
def top_category(entry: ActivityEntry) -> Category:
    cat = entry.activity.category
    return cat.parent if cat.parent_id else cat


def group_by(entries, key_fn) -> dict:
    groups = defaultdict(list)
    for e in entries:
        groups[key_fn(e)].append(e)
    return groups


def chart(chart_type: str, labels: list, datasets: list[dict], *, unit: str = "", stacked: bool = False,
          horizontal: bool = False, fill: bool = False, duration: bool = False) -> dict:
    """Specifica neutra di un grafico, convertita in Chart.js da static/js/charts.js."""
    return {
        "type": chart_type, "labels": labels, "datasets": datasets, "unit": unit, "stacked": stacked,
        "horizontal": horizontal, "fill": fill, "duration": duration,
    }


def _round(v):
    return None if v is None else round(v, 2)


def trend_chart(entries, period: Period, measure: Measure, series_fn=None, series_info=None,
                fill=False, stacked=False) -> dict:
    """Andamento nel tempo. Se series_fn è indicata, una serie per gruppo (es. per persona)."""
    granularity = buckets_for(period)
    keys = bucket_labels(period, granularity)
    by_bucket = group_by(entries, lambda e: bucket_key(to_local(e.occurred_at), granularity))
    if series_fn is None:
        data = [_round(aggregate(by_bucket.get(k, []), measure)) for k, _ in keys]
        datasets = [{"label": measure.label, "data": data, "color": "#4f46e5"}]
    else:
        datasets = []
        for sid, (label, color) in series_info.items():
            data = [_round(aggregate([e for e in by_bucket.get(k, []) if series_fn(e) == sid], measure))
                    for k, _ in keys]
            datasets.append({"label": label, "data": data, "color": color})
    return chart("line", [label for _, label in keys], datasets, unit=measure.unit, fill=fill, stacked=stacked,
                 duration=measure.is_duration)


def breakdown(entries, measure: Measure, key_fn, info_fn, limit: int | None = None) -> list[tuple]:
    """[(label, colore, valore)] ordinato per valore decrescente."""
    rows = []
    for key, items in group_by(entries, key_fn).items():
        label, color = info_fn(key, items)
        rows.append((label, color, aggregate(items, measure) or 0))
    rows.sort(key=lambda r: r[2], reverse=True)
    if limit and len(rows) > limit:
        rest = rows[limit:]
        rows = rows[:limit]
        if measure.aggregation == "sum":
            rows.append(("Altro", "#94a3b8", sum(r[2] for r in rest)))
    return rows


def category_breakdown(entries, measure, limit=7):
    return breakdown(entries, measure, lambda e: top_category(e).id,
                     lambda k, items: (top_category(items[0]).name, top_category(items[0]).color), limit)


def activity_breakdown(entries, measure, limit=10):
    return breakdown(entries, measure, lambda e: e.activity_id,
                     lambda k, items: (items[0].activity.name, items[0].activity.display_color), limit)


def member_breakdown(entries, measure):
    return breakdown(entries, measure, lambda e: e.performed_by_profile_id,
                     lambda k, items: (items[0].performed_by.display_name, items[0].performed_by.color))


def rows_chart(rows, chart_type="bar", measure: Measure | None = None, horizontal=False) -> dict:
    return chart(chart_type, [r[0] for r in rows],
                 [{"label": measure.label if measure else "", "data": [_round(r[2]) for r in rows],
                   "colors": [r[1] for r in rows]}],
                 unit=measure.unit if measure else "", horizontal=horizontal,
                 duration=bool(measure and measure.is_duration))


# --------------------------------------------------------------------------- KPI
def kpi_block(actor, entries, prev_entries, measure: Measure, profile_id: int | None, filters: StatsFilters) -> dict:
    """Indicatori sintetici per il periodo + finestre fisse (oggi, settimana, mese)."""
    today = local_today()
    windows = {
        "today": (today, today),
        "week": (today - timedelta(days=today.weekday()), today),
        "month": (today.replace(day=1), today),
    }
    window_counts = {}
    for name, (start, end) in windows.items():
        p = Period("custom", start, end)
        window_counts[name] = len(load_entries(actor, p, filters, profile_id=profile_id))
    current = aggregate(entries, measure)
    previous = aggregate(prev_entries, measure)
    delta = None
    if current is not None and previous:
        delta = round((current - previous) / previous * 100)
    return {
        "total": fmt_measure(current, measure),
        "total_raw": current,
        "previous": fmt_measure(previous, measure),
        "delta": delta,
        "count": len(entries),
        "time": fmt_hours(duration_seconds(entries)),
        "time_raw": duration_seconds(entries),
        "active_days": len({to_local(e.occurred_at).date() for e in entries}),
        "today": window_counts["today"],
        "week": window_counts["week"],
        "month": window_counts["month"],
    }


# --------------------------------------------------------------------------- heatmap
def heatmap(actor, filters: StatsFilters, profile_id: int | None, weeks: int = 53) -> dict:
    """Calendario delle ultime `weeks` settimane: conteggio registrazioni per giorno (livelli 0-4)."""
    today = local_today()
    end = today + timedelta(days=6 - today.weekday())
    start = end - timedelta(days=weeks * 7 - 1)
    entries = load_entries(actor, Period("custom", start, today), filters, profile_id=profile_id)
    counts = Counter(to_local(e.occurred_at).date() for e in entries)
    peak = max(counts.values()) if counts else 0
    columns, months = [], []
    d = start
    for w in range(weeks):
        column = []
        for _ in range(7):
            n = counts.get(d, 0)
            level = 0 if n == 0 or peak == 0 else min(4, 1 + int(3 * (n - 1) / max(peak - 1, 1)))
            column.append({"date": d, "count": n, "level": level, "future": d > today})
            d += timedelta(days=1)
        if column[0]["date"].day <= 7:
            months.append((w, MONTHS_SHORT_IT[column[0]["date"].month - 1]))
        columns.append(column)
    return {"columns": columns, "months": months, "total": sum(counts.values()), "peak": peak,
            "active_days": len(counts)}


# --------------------------------------------------------------------------- confronti
def compare_periods_chart(entries, prev_entries, measure, period: Period) -> dict:
    """Per categoria: periodo attuale vs precedente (barre affiancate)."""
    cats = {}
    for e in entries + prev_entries:
        c = top_category(e)
        cats[c.id] = c.name
    labels = list(cats.values())
    cur = group_by(entries, lambda e: top_category(e).id)
    prev = group_by(prev_entries, lambda e: top_category(e).id)
    return chart("bar", labels, [
        {"label": period.previous().label, "data": [_round(aggregate(prev.get(k, []), measure)) for k in cats],
         "color": SERIES_COLORS[1]},
        {"label": period.label, "data": [_round(aggregate(cur.get(k, []), measure)) for k in cats],
         "color": SERIES_COLORS[0]},
    ], unit=measure.unit, duration=measure.is_duration)


def year_over_year(actor, filters: StatsFilters, measure: Measure, year: int, profile_id=None) -> dict:
    """Mesi dell'anno scelto vs anno precedente (linee)."""
    datasets = []
    for idx, y in enumerate((year - 1, year)):
        entries = load_entries(actor, Period("year", date(y, 1, 1), date(y, 12, 31)), filters, profile_id=profile_id)
        by_month = group_by(entries, lambda e: to_local(e.occurred_at).month)
        datasets.append({"label": str(y), "data": [_round(aggregate(by_month.get(m, []), measure))
                                                   for m in range(1, 13)],
                         "color": SERIES_COLORS[1 - idx]})
    return chart("line", [m.capitalize() for m in MONTHS_SHORT_IT], datasets, unit=measure.unit,
                 duration=measure.is_duration)


def yearly_totals(actor, filters: StatsFilters, measure: Measure, years: int = 5, profile_id=None) -> dict:
    this_year = local_today().year
    labels, data = [], []
    for y in range(this_year - years + 1, this_year + 1):
        entries = load_entries(actor, Period("year", date(y, 1, 1), date(y, 12, 31)), filters, profile_id=profile_id)
        labels.append(str(y))
        data.append(_round(aggregate(entries, measure)))
    return chart("bar", labels, [{"label": measure.label, "data": data, "color": SERIES_COLORS[0]}],
                 unit=measure.unit, duration=measure.is_duration)


def radar_categories_by_member(entries, measure, members) -> dict:
    """Radar: per ogni persona il profilo sulle categorie (stessa misura per tutti)."""
    cats = {}
    for e in entries:
        c = top_category(e)
        cats[c.id] = c.name
    datasets = []
    for profile in members:
        mine = group_by([e for e in entries if e.performed_by_profile_id == profile.id], lambda e: top_category(e).id)
        datasets.append({"label": profile.display_name, "color": profile.color,
                         "data": [_round(aggregate(mine.get(k, []), measure)) or 0 for k in cats]})
    return chart("radar", list(cats.values()), datasets, unit=measure.unit, duration=measure.is_duration)


def personal_vs_family(actor, entries_me, entries_family, period, measure, member_count: int) -> dict:
    """Il mio andamento confrontato con la media per componente della famiglia."""
    granularity = buckets_for(period)
    keys = bucket_labels(period, granularity)
    mine = group_by(entries_me, lambda e: bucket_key(to_local(e.occurred_at), granularity))
    fam = group_by(entries_family, lambda e: bucket_key(to_local(e.occurred_at), granularity))
    divisor = max(member_count, 1)
    family_avg = []
    for k, _ in keys:
        value = aggregate(fam.get(k, []), measure)
        family_avg.append(_round(value / divisor if (value is not None and measure.aggregation == "sum") else value))
    return chart("line", [label for _, label in keys], [
        {"label": "Io", "data": [_round(aggregate(mine.get(k, []), measure)) for k, _ in keys],
         "color": SERIES_COLORS[0]},
        {"label": "Media per componente", "data": family_avg, "color": SERIES_COLORS[1], "dashed": True},
    ], unit=measure.unit, duration=measure.is_duration)


def to_decimal(value) -> Decimal:
    return Decimal(str(value or 0))
