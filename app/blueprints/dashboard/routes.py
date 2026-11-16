"""Dashboard personale, familiare e comparativa."""
from flask import render_template, request

from app.blueprints.dashboard import bp
from app.models import SCOPE_LABELS
from app.services import catalog_service, entry_service, stats_service
from app.services.period import PERIOD_LABELS, period_from_args
from app.services.stats_service import StatsFilters
from app.utils.security import family_required, get_current_membership
from app.utils.timezone import local_today

COMPARE_VIEWS = {
    "persone": "Tra persone",
    "periodi": "Tra mesi e anni",
    "categorie": "Tra categorie",
    "attivita": "Tra attività",
    "io-famiglia": "Io e la famiglia",
}


def _filters(actor, default_period="month"):
    args = request.args
    period = period_from_args(args, default_period)
    category_id = args.get("categoria", type=int)
    activity_id = args.get("attivita", type=int)
    measures = stats_service.available_measures(actor.family_id, activity_id)
    measure = stats_service.resolve_measure(measures, args.get("misura", "count"))
    filters = StatsFilters(
        period=period,
        profile_id=args.get("persona", type=int),
        category_id=category_id,
        activity_id=activity_id,
        scope=args.get("ambito") if args.get("ambito") in SCOPE_LABELS else None,
        measure=measure.key,
    )
    return filters, measure, measures


def _context(actor, filters, measures, **extra):
    args = {k: v for k, v in request.args.items() if v}
    return dict(
        filters=filters,
        period=filters.period,
        measures=measures,
        period_labels=PERIOD_LABELS,
        categories=catalog_service.category_choices(actor.family_id),
        activities=catalog_service.activity_choices(actor.family_id),
        profiles=entry_service.family_profiles(actor.family_id),
        scope_labels=SCOPE_LABELS,
        args=args,
        prev_args={**args, "rif": filters.period.previous().start.isoformat()},
        next_args={**args, "rif": filters.period.next().start.isoformat()},
        is_current=filters.period.start <= local_today() <= filters.period.end,
        **extra,
    )


@bp.route("/")
@family_required
def personal():
    actor = get_current_membership()
    filters, measure, measures = _filters(actor)
    me = actor.profile_id
    entries = stats_service.load_entries(actor, filters.period, filters, profile_id=me)
    prev = stats_service.load_entries(actor, filters.period.previous(), filters, profile_id=me)
    from app.services import goal_service

    return render_template(
        "dashboard/personal.html",
        **_context(actor, filters, measures),
        measure=measure,
        kpi=stats_service.kpi_block(actor, entries, prev, measure, me, filters),
        trend=stats_service.trend_chart(entries, filters.period, measure, fill=True),
        by_category=stats_service.rows_chart(stats_service.category_breakdown(entries, measure), "doughnut", measure),
        by_activity=stats_service.rows_chart(stats_service.activity_breakdown(entries, measure), "bar", measure,
                                             horizontal=True),
        compare=stats_service.compare_periods_chart(entries, prev, measure, filters.period),
        heat=stats_service.heatmap(actor, filters, me),
        goals=goal_service.dashboard_goals(actor, personal=True),
    )


@bp.route("/famiglia")
@family_required
def family():
    actor = get_current_membership()
    filters, measure, measures = _filters(actor)
    entries = stats_service.load_entries(actor, filters.period, filters)
    prev = stats_service.load_entries(actor, filters.period.previous(), filters)
    shared = [e for e in entries if e.scope == "family"]
    members = {}
    for e in entries:
        members[e.performed_by_profile_id] = (e.performed_by.display_name, e.performed_by.color)
    from app.services import goal_service

    return render_template(
        "dashboard/family.html",
        **_context(actor, filters, measures),
        measure=measure,
        kpi=stats_service.kpi_block(actor, entries, prev, measure, None, filters),
        shared_count=len(shared),
        shared_time=stats_service.fmt_hours(stats_service.duration_seconds(shared)),
        members_active=len(members),
        by_member=stats_service.rows_chart(stats_service.member_breakdown(entries, measure), "bar", measure),
        trend_members=stats_service.trend_chart(entries, filters.period, measure,
                                                series_fn=lambda e: e.performed_by_profile_id,
                                                series_info=members, fill=True, stacked=measure.aggregation == "sum"),
        trend_scope=stats_service.trend_chart(
            entries, filters.period, measure, series_fn=lambda e: e.scope,
            series_info={"personal": ("Personali", stats_service.SERIES_COLORS[0]),
                         "family": ("Condivise", stats_service.SERIES_COLORS[2])}),
        by_category=stats_service.rows_chart(stats_service.category_breakdown(entries, measure), "doughnut", measure),
        compare=stats_service.compare_periods_chart(entries, prev, measure, filters.period),
        heat=stats_service.heatmap(actor, filters, None),
        goals=goal_service.dashboard_goals(actor, personal=False),
    )


@bp.route("/confronti")
@family_required
def compare():
    actor = get_current_membership()
    view = request.args.get("vista", "persone")
    if view not in COMPARE_VIEWS:
        view = "persone"
    filters, measure, measures = _filters(actor)
    charts, notes = {}, []
    profiles = entry_service.family_profiles(actor.family_id)
    if view == "persone":
        entries = stats_service.load_entries(actor, filters.period, filters)
        info = {p.id: (p.display_name, p.color) for p in profiles}
        charts["Totale per persona"] = stats_service.rows_chart(
            stats_service.member_breakdown(entries, measure), "bar", measure)
        charts["Andamento per persona"] = stats_service.trend_chart(
            entries, filters.period, measure, series_fn=lambda e: e.performed_by_profile_id, series_info=info)
        charts["Profilo per categoria (radar)"] = stats_service.radar_categories_by_member(entries, measure, profiles)
    elif view == "periodi":
        year = request.args.get("anno", local_today().year, type=int)
        charts[f"Mese per mese: {year} vs {year - 1}"] = stats_service.year_over_year(actor, filters, measure, year)
        charts["Totale per anno"] = stats_service.yearly_totals(actor, filters, measure)
        entries = stats_service.load_entries(actor, filters.period, filters)
        prev = stats_service.load_entries(actor, filters.period.previous(), filters)
        charts[f"{filters.period.label} vs periodo precedente"] = stats_service.compare_periods_chart(
            entries, prev, measure, filters.period)
    elif view == "categorie":
        entries = stats_service.load_entries(actor, filters.period, filters)
        prev = stats_service.load_entries(actor, filters.period.previous(), filters)
        charts["Per categoria"] = stats_service.rows_chart(
            stats_service.category_breakdown(entries, measure, limit=12), "bar", measure)
        charts["Categorie: periodo attuale vs precedente"] = stats_service.compare_periods_chart(
            entries, prev, measure, filters.period)
        charts["Categorie per persona (radar)"] = stats_service.radar_categories_by_member(entries, measure, profiles)
    elif view == "attivita":
        entries = stats_service.load_entries(actor, filters.period, filters)
        charts["Per attività"] = stats_service.rows_chart(
            stats_service.activity_breakdown(entries, measure, limit=15), "bar", measure, horizontal=True)
        top = [r[0] for r in stats_service.activity_breakdown(entries, measure, limit=5) if r[0] != "Altro"]
        info = {}
        for e in entries:
            if e.activity.name in top:
                info[e.activity_id] = (e.activity.name, e.activity.display_color)
        charts["Andamento delle attività principali"] = stats_service.trend_chart(
            [e for e in entries if e.activity_id in info], filters.period, measure,
            series_fn=lambda e: e.activity_id, series_info=info)
    else:
        mine = stats_service.load_entries(actor, filters.period, filters, profile_id=actor.profile_id)
        everyone = stats_service.load_entries(actor, filters.period, filters)
        active_members = len({e.performed_by_profile_id for e in everyone}) or 1
        charts["Il mio andamento e la media della famiglia"] = stats_service.personal_vs_family(
            actor, mine, everyone, filters.period, measure, active_members)
        notes.append(f"La media è calcolata sui {active_members} componenti con almeno una registrazione nel periodo.")
    if measure.key != "count" and measure.aggregation != "sum":
        notes.append(f"La misura scelta è una {stats_service.AGG_LABELS[measure.aggregation]}: "
                     "i valori non vengono sommati tra le persone.")
    return render_template(
        "dashboard/compare.html", **_context(actor, filters, measures), measure=measure, view=view,
        views=COMPARE_VIEWS, charts=charts, notes=notes, year=request.args.get("anno", local_today().year, type=int),
    )
