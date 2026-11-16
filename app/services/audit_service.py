"""Scrittura dell'audit log. La commit è responsabilità del chiamante (stessa transazione)."""
from __future__ import annotations

import json
from typing import Any

from flask import has_request_context
from flask_login import current_user

from app.extensions import db
from app.models import AuditLog
from app.utils.security import client_ip


def log_action(
    action: str,
    *,
    family_id: int | None = None,
    entity: Any = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    details: dict | None = None,
    user_id: int | None = None,
) -> AuditLog:
    if entity is not None:
        entity_type = entity_type or entity.__tablename__
        entity_id = entity_id or getattr(entity, "id", None)
    if user_id is None and has_request_context() and current_user.is_authenticated:
        user_id = current_user.id
    entry = AuditLog(
        action=action,
        family_id=family_id,
        user_id=user_id,
        entity_type=entity_type,
        entity_id=entity_id,
        details_json=json.dumps(details, default=str, ensure_ascii=False) if details else None,
        ip_address=client_ip() if has_request_context() else None,
    )
    db.session.add(entry)
    return entry


ACTION_LABELS = {
    "auth.register": "Registrazione account",
    "auth.login": "Accesso",
    "auth.login_failed": "Accesso fallito",
    "auth.locked": "Account bloccato (troppi tentativi)",
    "auth.logout": "Uscita",
    "auth.password_changed": "Password modificata",
    "auth.password_reset_cli": "Password reimpostata da riga di comando",
    "family.created": "Famiglia creata",
    "family.renamed": "Famiglia rinominata",
    "family.deleted": "Famiglia eliminata",
    "family.member_joined": "Nuovo membro",
    "family.member_left": "Membro uscito",
    "family.member_removed": "Membro rimosso",
    "family.member_role_changed": "Ruolo modificato",
    "family.dependent_added": "Profilo dipendente creato",
    "family.invitation_created": "Invito creato",
    "family.invitation_revoked": "Invito revocato",
    "profile.updated": "Profilo modificato",
    "profile.avatar_changed": "Foto profilo cambiata",
    "profile.avatar_removed": "Foto profilo rimossa",
}


def action_label(action: str) -> str:
    return ACTION_LABELS.get(action, action)
