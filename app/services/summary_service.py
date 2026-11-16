"""Riepiloghi settimanali e mensili (pagina + notifica automatica)."""
from __future__ import annotations

from datetime import timedelta

from app.extensions import db
from app.models import FamilyMember, GoalEvent, Goal, Profile, User
from app.services import goal_service, stats_service
from app.services.notification_service import notify
from app.services.period import Period, period_for
from app.services.stats_service import Measure, StatsFilters
from app.utils.formatting import fmt_hours
from app.utils.timezone import local_today, to_local


def build(actor: FamilyMember, period: Period) -> dict:
    count = Measure("count", "Registrazioni")
    filters = StatsFilters(period=period)
    mine = stats_service.load_entries(actor, period, filters, profile_id=actor.profile_id)
    mine_prev = stats_service.load_entries(actor, period.previous(), filters, profile_id=actor.profile_id)
    family = stats_service.load_entries(actor, period, filters)
    start, end = period.utc_range
    completed = list(db.session.scalars(
        db.select(GoalEvent).join(Goal).where(
            Goal.id.in_(goal_service.visible_goals_query(actor).with_only_columns(Goal.id)),
            GoalEvent.event == "completed", GoalEvent.created_at >= start, GoalEvent.created_at < end)
    ))
    delta = None
    if mine_prev:
        delta = round((len(mine) - len(mine_prev)) / len(mine_prev) * 100)
    return {
        "period": period,
        "my_count": len(mine),
        "my_prev": len(mine_prev),
        "delta": delta,
        "my_time": fmt_hours(stats_service.duration_seconds(mine)),
        "my_days": len({to_local(e.occurred_at).date() for e in mine}),
        "my_activities": stats_service.activity_breakdown(mine, count, limit=8),
        "my_categories": stats_service.category_breakdown(mine, count),
        "family_count": len(family),
        "family_time": fmt_hours(stats_service.duration_seconds(family)),
        "family_members": stats_service.member_breakdown(family, count),
        "shared": len([e for e in family if e.scope == "family"]),
        "goals_completed": completed,
    }


def _users_with_family(flag: str):
    users = db.session.scalars(db.select(User).where(getattr(User, flag).is_(True), User.is_active_account.is_(True)))
    for user in users:
        if user.current_family_id and user.profile:
            member = db.session.scalar(db.select(FamilyMember).filter_by(
                family_id=user.current_family_id, profile_id=user.profile.id))
            if member:
                yield user, member


def send_due_summaries() -> int:
    """Crea (una sola volta) la notifica del riepilogo dell'ultima settimana/mese concluso."""
    today = local_today()
    sent = 0
    last_week = period_for("week", today - timedelta(days=7))
    last_month = period_for("month", today.replace(day=1) - timedelta(days=1))
    for flag, period, kind, label in (
        ("weekly_summary", last_week, "settimana", "Il riepilogo della settimana"),
        ("monthly_summary", last_month, "mese", f"Il riepilogo di {last_month.label.lower()}"),
    ):
        for user, member in _users_with_family(flag):
            data = build(member, period)
            body = f"{data['my_count']} registrazioni · {data['my_time']} · famiglia: {data['family_count']}"
            sent += notify([user.id], family_id=member.family_id, type="summary", title=label, body=body,
                           link=f"/riepiloghi?tipo={kind}&rif={period.start.isoformat()}",
                           dedupe_key=f"sum-{kind}-{member.family_id}-{period.start.isoformat()}")
    db.session.commit()
    return sent
