"""Obiettivi personali, familiari e individuali visibili alla famiglia.

Un obiettivo misura, in una finestra temporale, una di queste grandezze:
- count:    numero di registrazioni;
- quantity: somma delle quantità (richiede un'attività);
- metric:   valore di un indicatore, aggregato come previsto dall'indicatore
            (somma per km/durata, media per frequenza cardiaca, ...).

Finestra: dall'inizio alla scadenza (una tantum) oppure la settimana/mese/anno corrente
(ricorrente). Il progresso è sempre calcolato dai dati: nessun contatore da tenere allineato.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import or_

from app.extensions import db
from app.models import (
    ActivityEntry,
    Activity,
    Category,
    FamilyMember,
    Goal,
    GoalEvent,
    MetricDefinition,
    Profile,
    User,
)
from app.services import PermissionDenied, ServiceError
from app.services.audit_service import log_action
from app.services.common import get_family_object
from app.services.notification_service import notify
from app.services.period import local_date_range_utc, period_for
from app.utils.formatting import fmt_duration, fmt_number
from app.utils.timezone import local_today, utcnow


# --------------------------------------------------------------------------- permessi e visibilità
def visible_goals_query(actor: FamilyMember):
    return db.select(Goal).where(
        Goal.family_id == actor.family_id,
        or_(
            Goal.visibility == "family",
            Goal.scope == "family",
            Goal.owner_profile_id == actor.profile_id,
            Goal.created_by_user_id == actor.profile.user_id,
        ),
    )


def get_visible_goal(actor, goal_id) -> Goal | None:
    return db.session.scalar(visible_goals_query(actor).where(Goal.id == goal_id))


def can_edit(actor: FamilyMember, goal: Goal) -> bool:
    return actor.is_admin or goal.created_by_user_id == actor.profile.user_id or goal.owner_profile_id == actor.profile_id


def owner_choices(actor: FamilyMember) -> list[Profile]:
    from app.services.entry_service import performer_choices

    return performer_choices(actor)


# --------------------------------------------------------------------------- calcolo
@dataclass
class Progress:
    goal: Goal
    start: date
    end: date
    period_key: str
    value: float
    target: float
    pct: int
    value_label: str
    target_label: str
    days_left: int | None

    @property
    def done(self) -> bool:
        return self.value >= self.target


def window(goal: Goal, today: date | None = None) -> tuple[date, date, str]:
    today = today or local_today()
    if goal.recurrence == "none":
        end = goal.end_date or max(today, goal.start_date)
        return goal.start_date, end, ""
    kind = {"weekly": "week", "monthly": "month", "yearly": "year"}[goal.recurrence]
    ref = min(max(today, goal.start_date), goal.end_date) if goal.end_date else max(today, goal.start_date)
    period = period_for(kind, ref)
    start = max(period.start, goal.start_date)
    end = min(period.end, goal.end_date) if goal.end_date else period.end
    return start, end, period.start.isoformat()


def _entries_query(goal: Goal, start: date, end: date):
    utc_start, utc_end = local_date_range_utc(start, end)
    query = (
        db.select(ActivityEntry).join(Activity, ActivityEntry.activity_id == Activity.id)
        .where(ActivityEntry.family_id == goal.family_id, ActivityEntry.deleted_at.is_(None),
               ActivityEntry.occurred_at >= utc_start, ActivityEntry.occurred_at < utc_end)
    )
    if goal.owner_profile_id:
        query = query.where(ActivityEntry.performed_by_profile_id == goal.owner_profile_id)
    else:
        query = query.where(ActivityEntry.visibility == "family")
    if goal.activity_id:
        query = query.where(ActivityEntry.activity_id == goal.activity_id)
    elif goal.category_id:
        sub = db.select(Category.id).where(or_(Category.id == goal.category_id, Category.parent_id == goal.category_id))
        query = query.where(Activity.category_id.in_(sub))
    return query


def _format(goal: Goal, value: float) -> str:
    if goal.target_type == "metric" and goal.metric:
        if goal.metric.data_type == "duration":
            return fmt_duration(value)
        return f"{fmt_number(value, 1)}{' ' + goal.metric.unit if goal.metric.unit else ''}"
    if goal.target_type == "quantity" and goal.activity:
        return f"{fmt_number(value, 1)} {goal.activity.count_label}"
    return f"{fmt_number(value, 0)} registrazioni"


def compute(goal: Goal, today: date | None = None) -> Progress:
    today = today or local_today()
    start, end, key = window(goal, today)
    entries = list(db.session.scalars(_entries_query(goal, start, end)))
    if goal.target_type == "count":
        value = float(len(entries))
    elif goal.target_type == "quantity":
        value = float(sum(e.quantity for e in entries))
    else:
        values = [float(v.value_numeric) for e in entries for v in e.metric_values
                  if v.metric_definition_id == goal.metric_definition_id and v.value_numeric is not None]
        agg = goal.metric.aggregation if goal.metric else "sum"
        if not values:
            value = 0.0
        elif agg == "sum":
            value = sum(values)
        elif agg == "avg":
            value = sum(values) / len(values)
        elif agg == "max":
            value = max(values)
        else:
            value = min(values)
    # per gli indicatori di durata il target è espresso in minuti, i valori in secondi
    target = float(goal.target_value) * (60 if goal.metric and goal.metric.data_type == "duration" else 1)
    pct = int(min(100, round(value / target * 100))) if target else 0
    days_left = (end - today).days if end >= today else None
    return Progress(goal, start, end, key, value, target, pct, _format(goal, value), _format(goal, target), days_left)


def evaluate(goal: Goal, today: date | None = None) -> Progress:
    """Aggiorna lo stato dell'obiettivo e registra eventi/notifiche (idempotente)."""
    today = today or local_today()
    progress = compute(goal, today)
    if goal.status != "active":
        return progress
    link = f"/obiettivi/{goal.id}"
    recipients = _recipients(goal)
    if progress.pct >= 50 and _add_event(goal, "progress_50", progress.period_key, progress.value):
        notify(recipients, family_id=goal.family_id, type="goal", title=f"A metà strada: {goal.title}",
               body=f"{progress.value_label} su {progress.target_label}", link=link,
               dedupe_key=f"goal{goal.id}-50-{progress.period_key}")
    if progress.done and _add_event(goal, "completed", progress.period_key, progress.value):
        notify(recipients, family_id=goal.family_id, type="goal", title=f"Obiettivo raggiunto: {goal.title} 🎉",
               body=f"{progress.value_label} su {progress.target_label}", link=link,
               dedupe_key=f"goal{goal.id}-done-{progress.period_key}")
        if goal.recurrence == "none":
            goal.status = "completed"
            goal.completed_at = utcnow()
    if goal.end_date and goal.end_date < today and goal.status == "active":
        # periodo dell'obiettivo concluso senza raggiungere il traguardo (o ricorrenza terminata)
        if goal.recurrence != "none" and progress.done:
            goal.status = "completed"
            goal.completed_at = utcnow()
        else:
            goal.status = "expired"
            if _add_event(goal, "expired", "", progress.value):
                notify(recipients, family_id=goal.family_id, type="goal", title=f"Obiettivo scaduto: {goal.title}",
                       body=f"Risultato: {progress.value_label} su {progress.target_label}", link=link,
                       dedupe_key=f"goal{goal.id}-expired")
    return progress


def _add_event(goal: Goal, event: str, period_key: str, value) -> bool:
    exists = db.session.scalar(db.select(GoalEvent.id).filter_by(goal_id=goal.id, event=event, period_key=period_key))
    if exists:
        return False
    db.session.add(GoalEvent(goal_id=goal.id, event=event, period_key=period_key, value=Decimal(str(round(value, 4)))))
    return True


def _recipients(goal: Goal) -> list[int]:
    if goal.owner_profile_id and goal.scope == "personal":
        ids = {goal.created_by_user_id}
        if goal.owner and goal.owner.user_id:
            ids.add(goal.owner.user_id)
    else:
        ids = set(db.session.scalars(
            db.select(Profile.user_id).join(FamilyMember)
            .where(FamilyMember.family_id == goal.family_id, Profile.user_id.is_not(None))
        ))
    users = db.session.scalars(db.select(User).where(User.id.in_([i for i in ids if i])))
    return [u.id for u in users if u.goal_notifications]


def evaluate_family_goals(family_id: int) -> None:
    goals = db.session.scalars(db.select(Goal).filter_by(family_id=family_id, status="active"))
    for goal in goals:
        evaluate(goal)
    db.session.commit()


def evaluate_all() -> int:
    """Usato dal job periodico: aggiorna le scadenze di tutte le famiglie."""
    family_ids = set(db.session.scalars(db.select(Goal.family_id).filter_by(status="active")))
    for family_id in family_ids:
        evaluate_family_goals(family_id)
    return len(family_ids)


# --------------------------------------------------------------------------- elenco
def list_goals(actor: FamilyMember, status: str = "active") -> list[Progress]:
    query = visible_goals_query(actor)
    query = query.where(Goal.status == "active") if status == "active" else query.where(Goal.status != "active")
    goals = list(db.session.scalars(query.order_by(Goal.end_date.is_(None), Goal.end_date, Goal.title)))
    return [compute(g) for g in goals]


def dashboard_goals(actor: FamilyMember, personal: bool) -> list[Progress]:
    query = visible_goals_query(actor).where(Goal.status == "active")
    if personal:
        query = query.where(Goal.owner_profile_id == actor.profile_id)
    else:
        query = query.where(or_(Goal.scope == "family", Goal.visibility == "family"))
    return [compute(g) for g in db.session.scalars(query.order_by(Goal.title))]


# --------------------------------------------------------------------------- CRUD
def _apply(actor, goal: Goal, data: dict) -> None:
    title = (data.get("title") or "").strip()
    if not title:
        raise ServiceError("Il titolo è obbligatorio.")
    scope = data.get("scope")
    if scope not in ("personal", "family"):
        raise ServiceError("Tipo di obiettivo non valido.")
    owner_id = data.get("owner_profile_id") if scope == "personal" else None
    if scope == "personal":
        if owner_id not in {p.id for p in owner_choices(actor)}:
            raise PermissionDenied("Non puoi creare obiettivi per questa persona.")
    elif not actor.is_admin:
        raise PermissionDenied("Solo gli amministratori creano obiettivi familiari.")
    target_type = data.get("target_type")
    activity = get_family_object(Activity, data.get("activity_id"), actor.family_id) if data.get("activity_id") else None
    category = get_family_object(Category, data.get("category_id"), actor.family_id) if data.get("category_id") else None
    metric = None
    if target_type == "quantity" and activity is None:
        raise ServiceError("Per un obiettivo di quantità scegli un'attività.")
    if target_type == "metric":
        metric = db.session.get(MetricDefinition, data.get("metric_definition_id") or 0)
        if metric is None or metric.activity.family_id != actor.family_id or not metric.is_numeric \
                or metric.data_type == "boolean":
            raise ServiceError("Scegli un indicatore numerico valido.")
        activity = metric.activity
    elif target_type not in ("count", "quantity"):
        raise ServiceError("Tipo di misura non valido.")
    target = Decimal(str(data.get("target_value") or 0))
    if target <= 0:
        raise ServiceError("Il traguardo deve essere maggiore di zero.")
    recurrence = data.get("recurrence")
    if recurrence not in ("none", "weekly", "monthly", "yearly"):
        raise ServiceError("Ricorrenza non valida.")
    start, end = data.get("start_date") or local_today(), data.get("end_date")
    if recurrence == "none" and end is None:
        raise ServiceError("Un obiettivo una tantum deve avere una scadenza.")
    if end and end < start:
        raise ServiceError("La scadenza non può precedere l'inizio.")
    goal.title, goal.description = title, (data.get("description") or "").strip() or None
    goal.scope, goal.owner_profile_id = scope, owner_id
    goal.visibility = "family" if scope == "family" else data.get("visibility", "family")
    goal.target_type, goal.target_value = target_type, target
    goal.activity_id = activity.id if activity else None
    goal.category_id = category.id if (category and not activity) else None
    goal.metric_definition_id = metric.id if metric else None
    goal.recurrence, goal.start_date, goal.end_date = recurrence, start, end


def create_goal(actor: FamilyMember, data: dict) -> Goal:
    goal = Goal(family_id=actor.family_id, created_by_user_id=actor.profile.user_id)
    _apply(actor, goal, data)
    db.session.add(goal)
    db.session.flush()
    db.session.add(GoalEvent(goal_id=goal.id, event="created", period_key=""))
    log_action("goal.created", family_id=actor.family_id, entity=goal, details={"title": goal.title})
    evaluate(goal)
    db.session.commit()
    return goal


def update_goal(actor: FamilyMember, goal: Goal, data: dict) -> None:
    if not can_edit(actor, goal):
        raise PermissionDenied("Non puoi modificare questo obiettivo.")
    _apply(actor, goal, data)
    if goal.status in ("expired", "completed") and (goal.end_date is None or goal.end_date >= local_today()):
        goal.status = "active"  # riaperto (es. scadenza prorogata)
        goal.completed_at = None
    log_action("goal.updated", family_id=actor.family_id, entity=goal, details={"title": goal.title})
    evaluate(goal)
    db.session.commit()


def set_archived(actor: FamilyMember, goal: Goal, archived: bool) -> None:
    if not can_edit(actor, goal):
        raise PermissionDenied("Non puoi modificare questo obiettivo.")
    goal.status = "archived" if archived else "active"
    db.session.add(GoalEvent(goal_id=goal.id, event="archived" if archived else "reopened",
                             period_key=utcnow().isoformat()))
    if not archived:
        evaluate(goal)
    db.session.commit()


def delete_goal(actor: FamilyMember, goal: Goal) -> None:
    if not can_edit(actor, goal):
        raise PermissionDenied("Non puoi eliminare questo obiettivo.")
    log_action("goal.deleted", family_id=actor.family_id, details={"title": goal.title})
    db.session.delete(goal)
    db.session.commit()


EVENT_LABELS = {
    "created": "Creato",
    "progress_50": "Raggiunto il 50%",
    "completed": "Traguardo raggiunto",
    "expired": "Scaduto",
    "archived": "Archiviato",
    "reopened": "Riaperto",
}


def history_periods(goal: Goal, periods: int = 8) -> list[Progress]:
    """Per gli obiettivi ricorrenti: risultato delle ultime N settimane/mesi/anni."""
    if goal.recurrence == "none":
        return []
    result, today = [], local_today()
    step = {"weekly": timedelta(days=7)}.get(goal.recurrence)
    ref = today
    for _ in range(periods):
        if ref < goal.start_date:
            break
        result.append(compute(goal, ref))
        if step:
            ref = ref - step
        elif goal.recurrence == "monthly":
            ref = (ref.replace(day=1) - timedelta(days=1))
        else:
            ref = date(ref.year - 1, 12, 31)
    return result
