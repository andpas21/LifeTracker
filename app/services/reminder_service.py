"""Promemoria personali: calcolo della prossima esecuzione e invio come notifica in-app."""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta

from app.extensions import db
from app.models import Activity, FamilyMember, Reminder
from app.services import PermissionDenied, ServiceError
from app.services.common import get_family_object
from app.services.notification_service import notify
from app.utils.timezone import local_now, to_local, to_utc, utcnow

FREQUENCY_LABELS = {"once": "Una volta", "daily": "Ogni giorno", "weekly": "Ogni settimana", "monthly": "Ogni mese"}


def next_occurrence(reminder: Reminder, after: datetime) -> datetime | None:
    """Prossima esecuzione (ora locale, naive) strettamente successiva ad `after` (ora locale, naive)."""
    t = reminder.time_of_day
    start = reminder.start_date
    if reminder.frequency == "once":
        candidate = datetime.combine(start, t)
        return candidate if candidate > after else None
    day = max(after.date(), start)
    for _ in range(400):
        candidate = datetime.combine(day, t)
        if candidate > after and _matches(reminder, day):
            return candidate
        day += timedelta(days=1)
    return None


def _matches(reminder: Reminder, day: date) -> bool:
    if reminder.frequency == "daily":
        return True
    if reminder.frequency == "weekly":
        return day.weekday() in (reminder.weekday_list or [reminder.start_date.weekday()])
    if reminder.frequency == "monthly":
        wanted = reminder.day_of_month or reminder.start_date.day
        last = calendar.monthrange(day.year, day.month)[1]
        return day.day == min(wanted, last)
    return False


def schedule(reminder: Reminder, after_utc: datetime | None = None) -> None:
    after_local = to_local(after_utc).replace(tzinfo=None) if after_utc else local_now().replace(tzinfo=None)
    nxt = next_occurrence(reminder, after_local)
    reminder.next_run_at = to_utc(nxt) if nxt else None


def list_for(actor: FamilyMember) -> list[Reminder]:
    return list(db.session.scalars(
        db.select(Reminder).filter_by(family_id=actor.family_id, user_id=actor.profile.user_id)
        .order_by(Reminder.is_active.desc(), Reminder.time_of_day)
    ))


def get_own(actor: FamilyMember, reminder_id: int) -> Reminder | None:
    return db.session.scalar(db.select(Reminder).filter_by(
        id=reminder_id, family_id=actor.family_id, user_id=actor.profile.user_id))


def save(actor: FamilyMember, reminder: Reminder | None, data: dict) -> Reminder:
    if data["frequency"] not in FREQUENCY_LABELS:
        raise ServiceError("Frequenza non valida.")
    weekdays = sorted({int(d) for d in data.get("weekdays") or [] if 0 <= int(d) <= 6})
    if data["frequency"] == "weekly" and not weekdays:
        raise ServiceError("Scegli almeno un giorno della settimana.")
    activity = None
    if data.get("activity_id"):
        activity = get_family_object(Activity, data["activity_id"], actor.family_id)
        if activity is None:
            raise ServiceError("Attività non valida.")
    if reminder is None:
        reminder = Reminder(family_id=actor.family_id, user_id=actor.profile.user_id)
        db.session.add(reminder)
    elif reminder.user_id != actor.profile.user_id:
        raise PermissionDenied("Promemoria non tuo.")
    reminder.title = data["title"].strip()
    reminder.message = (data.get("message") or "").strip() or None
    reminder.activity_id = activity.id if activity else None
    reminder.frequency = data["frequency"]
    reminder.time_of_day = data["time_of_day"]
    reminder.start_date = data["start_date"]
    reminder.weekdays = ",".join(str(d) for d in weekdays) if data["frequency"] == "weekly" else None
    reminder.day_of_month = data.get("day_of_month") if data["frequency"] == "monthly" else None
    reminder.is_active = True
    schedule(reminder)
    if reminder.next_run_at is None:
        raise ServiceError("La data e l'ora indicate sono già passate.")
    db.session.commit()
    return reminder


def toggle(actor: FamilyMember, reminder: Reminder) -> None:
    reminder.is_active = not reminder.is_active
    if reminder.is_active:
        schedule(reminder)
        if reminder.next_run_at is None:
            reminder.is_active = False
            db.session.commit()
            raise ServiceError("Il promemoria è già scaduto: modificane la data.")
    db.session.commit()


def delete(actor: FamilyMember, reminder: Reminder) -> None:
    db.session.delete(reminder)
    db.session.commit()


def run_due(now: datetime | None = None) -> int:
    """Invia i promemoria scaduti come notifiche. Restituisce quanti ne ha inviati."""
    now = now or utcnow()
    due = list(db.session.scalars(
        db.select(Reminder).where(Reminder.is_active.is_(True), Reminder.next_run_at.is_not(None),
                                  Reminder.next_run_at <= now)
    ))
    sent = 0
    for reminder in due:
        link = f"/registrazioni/nuova?attivita={reminder.activity_id}" if reminder.activity_id else "/registrazioni/rapida"
        sent += notify([reminder.user_id], family_id=reminder.family_id, type="reminder", title=reminder.title,
                       body=reminder.message, link=link,
                       dedupe_key=f"rem{reminder.id}-{reminder.next_run_at.isoformat(timespec='minutes')}")
        reminder.last_sent_at = now
        schedule(reminder, after_utc=max(now, reminder.next_run_at))
        if reminder.next_run_at is None:
            reminder.is_active = False
    db.session.commit()
    return sent
