"""Tutti i modelli SQLAlchemy.

Importarli qui garantisce che Alembic (flask db migrate) li veda tutti.
"""
from app.models.audit import AuditLog
from app.models.family import (
    ROLE_ADMIN,
    ROLE_DEPENDENT,
    ROLE_LABELS,
    ROLE_MEMBER,
    ROLES,
    Family,
    FamilyInvitation,
    FamilyMember,
    Profile,
)
from app.models.user import THEMES, User

__all__ = [
    "AuditLog",
    "Family",
    "FamilyInvitation",
    "FamilyMember",
    "Profile",
    "User",
    "ROLES",
    "ROLE_ADMIN",
    "ROLE_MEMBER",
    "ROLE_DEPENDENT",
    "ROLE_LABELS",
    "THEMES",
]
