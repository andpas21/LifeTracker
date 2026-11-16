"""Calendario: vista mensile, settimanale e giornaliera con riepilogo del giorno."""
from collections import defaultdict
from datetime import timedelta

from flask import render_template, request

from app.blueprints.calendar import bp
from app.extensions import db
from app.services import catalog_service, entry_service, stats_service
from app.services.entry_service import EntryFilters
from app.services.period import MONTHS_IT, WEEKDAYS_SHORT_IT, Period, add_months, parse_date, period_for
from app.utils.formatting import fmt_hours
from app.utils.security import family_required, get_current_membership
from app.utils.timezone import local_today, to_local

VIEWS = {"mese": "Mese", "settimana": "Settimana", "giorno": "Giorno"}


def _entries_by_day(actor, start, end, profile_id, category_id):
    utc_start, utc_end = Period("custom", start, end).utc_range
    query = entry_service.filtered_query(actor, EntryFilters(
        profile_id=profile_id, category_id=category_id, date_from=utc_start, date_to=utc_end))
    days = defaultdict(list)
    for e in db.session.scalars(query):
        days[to_local(e.occurred_at).date()].append(e)
    for items in days.values():
        items.sort(key=lambda e: e.occurred_at)
    return days


def _summary(entries):
    measure = stats_service.Measure("count", "Registrazioni")
    return {
        "count": len(entries),
        "time": fmt_hours(stats_service.duration_seconds(entries)),
        "has_time": stats_service.duration_seconds(entries) > 0,
        "categories": stats_service.category_breakdown(entries, measure, limit=6),
        "people": stats_service.member_breakdown(entries, measure),
    }


@bp.route("/")
@family_required
def index():
    actor = get_current_membership()
    view = request.args.get("vista", "mese")
    if view not in VIEWS:
        view = "mese"
    day = parse_date(request.args.get("data")) or local_today()
    profile_id = request.args.get("persona", type=int)
    category_id = request.args.get("categoria", type=int)
    today = local_today()

    if view == "mese":
        month = period_for("month", day)
        grid_start = month.start - timedelta(days=month.start.weekday())
        grid_end = month.end + timedelta(days=6 - month.end.weekday())
        days = _entries_by_day(actor, grid_start, grid_end, profile_id, category_id)
        weeks, d = [], grid_start
        while d <= grid_end:
            weeks.append([d + timedelta(days=i) for i in range(7)])
            d += timedelta(days=7)
        title = f"{MONTHS_IT[day.month - 1].capitalize()} {day.year}"
        prev_day, next_day = add_months(month.start, -1), add_months(month.start, 1)
        context = {"weeks": weeks, "month": day.month}
        summary_entries = [e for k, v in days.items() if month.start <= k <= month.end for e in v]
    elif view == "settimana":
        week = period_for("week", day)
        days = _entries_by_day(actor, week.start, week.end, profile_id, category_id)
        week_days = [week.start + timedelta(days=i) for i in range(7)]
        title = f"{week.start.strftime('%d/%m')} – {week.end.strftime('%d/%m/%Y')}"
        prev_day, next_day = week.start - timedelta(days=7), week.start + timedelta(days=7)
        context = {"week_days": week_days}
        summary_entries = [e for v in days.values() for e in v]
    else:
        days = _entries_by_day(actor, day, day, profile_id, category_id)
        title = day.strftime("%d/%m/%Y")
        prev_day, next_day = day - timedelta(days=1), day + timedelta(days=1)
        context = {}
        summary_entries = days.get(day, [])

    args = {k: v for k, v in request.args.items() if v and k not in ("data", "vista")}
    return render_template(
        "calendar/index.html", view=view, views=VIEWS, day=day, today=today, days=days, title=title,
        prev_day=prev_day, next_day=next_day, args=args, weekdays=WEEKDAYS_SHORT_IT,
        summary=_summary(summary_entries), profiles=entry_service.family_profiles(actor.family_id),
        categories=catalog_service.category_choices(actor.family_id), profile_id=profile_id,
        category_id=category_id, top_category=stats_service.top_category, **context,
    )
