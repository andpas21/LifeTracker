"""Periodi di analisi (giorno, settimana, mese, trimestre, semestre, anno, personalizzato).

I confini si calcolano sulle date *locali* (Europe/Rome) e poi si convertono in UTC
per interrogare il database: così il cambio dell'ora legale è gestito correttamente.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from app.utils.timezone import local_today, to_utc

PERIOD_LABELS = {
    "day": "Giorno",
    "week": "Settimana",
    "month": "Mese",
    "quarter": "Trimestre",
    "semester": "Semestre",
    "year": "Anno",
    "custom": "Personalizzato",
}

MONTHS_IT = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
             "settembre", "ottobre", "novembre", "dicembre"]
MONTHS_SHORT_IT = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"]
WEEKDAYS_IT = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
WEEKDAYS_SHORT_IT = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]


@dataclass
class Period:
    kind: str
    start: date  # incluso
    end: date  # incluso

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def utc_range(self) -> tuple[datetime, datetime]:
        return local_date_range_utc(self.start, self.end)

    @property
    def label(self) -> str:
        if self.kind == "day":
            return f"{WEEKDAYS_IT[self.start.weekday()]} {self.start.day} {MONTHS_IT[self.start.month - 1]} {self.start.year}"
        if self.kind == "month":
            return f"{MONTHS_IT[self.start.month - 1].capitalize()} {self.start.year}"
        if self.kind == "year":
            return str(self.start.year)
        if self.kind == "quarter":
            return f"{(self.start.month - 1) // 3 + 1}° trimestre {self.start.year}"
        if self.kind == "semester":
            return f"{1 if self.start.month <= 6 else 2}° semestre {self.start.year}"
        return f"{self.start.strftime('%d/%m/%Y')} – {self.end.strftime('%d/%m/%Y')}"

    def previous(self) -> "Period":
        """Periodo precedente della stessa durata (per i confronti)."""
        if self.kind in ("month", "quarter", "semester", "year"):
            months = {"month": 1, "quarter": 3, "semester": 6, "year": 12}[self.kind]
            return period_for(self.kind, add_months(self.start, -months))
        length = self.days
        return Period(self.kind, self.start - timedelta(days=length), self.start - timedelta(days=1))

    def next(self) -> "Period":
        if self.kind in ("month", "quarter", "semester", "year"):
            months = {"month": 1, "quarter": 3, "semester": 6, "year": 12}[self.kind]
            return period_for(self.kind, add_months(self.start, months))
        length = self.days
        return Period(self.kind, self.end + timedelta(days=1), self.end + timedelta(days=length))


def add_months(d: date, months: int) -> date:
    index = d.year * 12 + d.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def local_date_range_utc(start: date, end: date) -> tuple[datetime, datetime]:
    """[inizio del giorno start, inizio del giorno dopo end) in UTC."""
    return to_utc(datetime.combine(start, time.min)), to_utc(datetime.combine(end + timedelta(days=1), time.min))


def period_for(kind: str, ref: date | None = None) -> Period:
    ref = ref or local_today()
    if kind == "day":
        return Period(kind, ref, ref)
    if kind == "week":
        start = ref - timedelta(days=ref.weekday())
        return Period(kind, start, start + timedelta(days=6))
    if kind in ("month", "quarter", "semester", "year"):
        months = {"month": 1, "quarter": 3, "semester": 6, "year": 12}[kind]
        first_month = ((ref.month - 1) // months) * months + 1
        start = date(ref.year, first_month, 1)
        end = add_months(start, months) - timedelta(days=1)
        return Period(kind, start, end)
    raise ValueError(kind)


def parse_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def period_from_args(args, default: str = "month") -> Period:
    """Legge ?periodo=...&rif=YYYY-MM-DD&da=...&a=... dai parametri della richiesta."""
    kind = args.get("periodo", default)
    if kind == "custom":
        start, end = parse_date(args.get("da")), parse_date(args.get("a"))
        if start and end and start <= end and (end - start).days <= 3660:
            return Period("custom", start, end)
        kind = default
    if kind not in PERIOD_LABELS:
        kind = default
    return period_for(kind, parse_date(args.get("rif")))


def buckets_for(period: Period) -> str:
    """Granularità dei grafici temporali in base alla lunghezza del periodo."""
    if period.days <= 1:
        return "hour"
    if period.days <= 62:
        return "day"
    if period.days <= 200:
        return "week"
    return "month"


def bucket_key(local_dt: datetime, granularity: str) -> date | int:
    d = local_dt.date()
    if granularity == "hour":
        return local_dt.hour
    if granularity == "day":
        return d
    if granularity == "week":
        return d - timedelta(days=d.weekday())
    return date(d.year, d.month, 1)


def bucket_labels(period: Period, granularity: str) -> list[tuple[object, str]]:
    """Tutte le chiavi del periodo (anche quelle senza dati) con l'etichetta da mostrare."""
    result = []
    if granularity == "hour":
        return [(h, f"{h:02d}:00") for h in range(24)]
    if granularity == "day":
        d = period.start
        while d <= period.end:
            result.append((d, f"{d.day} {MONTHS_SHORT_IT[d.month - 1]}"))
            d += timedelta(days=1)
    elif granularity == "week":
        d = period.start - timedelta(days=period.start.weekday())
        while d <= period.end:
            result.append((d, f"sett. {d.day} {MONTHS_SHORT_IT[d.month - 1]}"))
            d += timedelta(days=7)
    else:
        d = date(period.start.year, period.start.month, 1)
        while d <= period.end:
            result.append((d, f"{MONTHS_SHORT_IT[d.month - 1]} {str(d.year)[2:]}"))
            d = add_months(d, 1)
    return result
