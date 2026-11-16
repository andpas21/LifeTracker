"""Notifiche in-app (campanella). Usate da obiettivi, promemoria e riepiloghi."""
from __future__ import annotations

from app.extensions import db
from app.models import Notification, User


def notify(user_ids, *, family_id: int | None, type: str, title: str, body: str | None = None,
           link: str | None = None, dedupe_key: str | None = None) -> int:
    """Crea una notifica per ogni utente. Con dedupe_key non crea doppioni. Restituisce quante ne ha create."""
    created = 0
    for user_id in set(u for u in user_ids if u):
        if dedupe_key and db.session.scalar(
            db.select(Notification.id).filter_by(user_id=user_id, dedupe_key=dedupe_key)
        ):
            continue
        db.session.add(Notification(user_id=user_id, family_id=family_id, type=type, title=title[:160],
                                    body=(body or None) and body[:500], link=link, dedupe_key=dedupe_key))
        created += 1
    return created


def unread_count(user: User) -> int:
    return db.session.scalar(
        db.select(db.func.count()).select_from(Notification).filter_by(user_id=user.id, is_read=False)
    )


def latest(user: User, limit: int = 50) -> list[Notification]:
    return list(db.session.scalars(
        db.select(Notification).filter_by(user_id=user.id)
        .order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit)
    ))


def mark_read(user: User, notification_id: int | None = None) -> Notification | None:
    query = db.update(Notification).where(Notification.user_id == user.id, Notification.is_read.is_(False))
    item = None
    if notification_id is not None:
        item = db.session.scalar(db.select(Notification).filter_by(id=notification_id, user_id=user.id))
        if item is None:
            return None
        query = query.where(Notification.id == notification_id)
    db.session.execute(query.values(is_read=True))
    db.session.commit()
    return item


def delete_read(user: User) -> None:
    db.session.execute(db.delete(Notification).where(Notification.user_id == user.id, Notification.is_read.is_(True)))
    db.session.commit()
