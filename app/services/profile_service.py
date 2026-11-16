"""Dati personali e foto profilo (per utenti e profili dipendenti)."""
from __future__ import annotations

from datetime import date

from flask import current_app
from werkzeug.datastructures import FileStorage

from app.extensions import db
from app.models import Profile
from app.services.audit_service import log_action
from app.utils.uploads import delete_upload, save_image

AVATAR_DIR = "avatars"


def update_profile(
    profile: Profile,
    *,
    display_name: str,
    birth_date: date | None,
    color: str,
    bio: str | None,
    family_id: int | None = None,
) -> None:
    changes = {}
    for field, value in (
        ("display_name", display_name.strip()),
        ("birth_date", birth_date),
        ("color", color.lower()),
        ("bio", (bio or "").strip() or None),
    ):
        if getattr(profile, field) != value:
            changes[field] = {"from": getattr(profile, field), "to": value}
            setattr(profile, field, value)
    if changes:
        log_action("profile.updated", family_id=family_id, entity=profile, details=changes)
    db.session.commit()


def set_avatar(profile: Profile, file: FileStorage, family_id: int | None = None) -> None:
    """Salva la nuova foto (validata e ri-codificata) e cancella la precedente."""
    new_name = save_image(file, AVATAR_DIR, current_app.config["AVATAR_SIZE"])
    old_name = profile.avatar_filename
    profile.avatar_filename = new_name
    log_action("profile.avatar_changed", family_id=family_id, entity=profile)
    db.session.commit()
    delete_upload(AVATAR_DIR, old_name)


def remove_avatar(profile: Profile, family_id: int | None = None) -> None:
    old_name = profile.avatar_filename
    if not old_name:
        return
    profile.avatar_filename = None
    log_action("profile.avatar_removed", family_id=family_id, entity=profile)
    db.session.commit()
    delete_upload(AVATAR_DIR, old_name)
