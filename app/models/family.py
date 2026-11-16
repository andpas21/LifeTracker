"""Famiglie, persone (profili), appartenenze e inviti."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.mixins import TimestampMixin
from app.utils.timezone import utcnow

ROLE_ADMIN = "admin"
ROLE_MEMBER = "member"
ROLE_DEPENDENT = "dependent"
ROLES = (ROLE_ADMIN, ROLE_MEMBER, ROLE_DEPENDENT)
ROLE_LABELS = {
    ROLE_ADMIN: "Amministratore",
    ROLE_MEMBER: "Membro",
    ROLE_DEPENDENT: "Profilo dipendente",
}


class Family(TimestampMixin, db.Model):
    __tablename__ = "families"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(db.String(120), nullable=False)
    timezone: Mapped[str] = mapped_column(db.String(64), default="Europe/Rome", nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(
        db.ForeignKey("users.id", ondelete="SET NULL", use_alter=True), nullable=True
    )

    memberships: Mapped[list["FamilyMember"]] = relationship(
        back_populates="family", cascade="all, delete-orphan", passive_deletes=True
    )
    invitations: Mapped[list["FamilyInvitation"]] = relationship(
        back_populates="family", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:
        return f"<Family {self.id} {self.name}>"


class Profile(TimestampMixin, db.Model):
    """Una persona. Ha un account (user_id) oppure è un profilo dipendente (user_id NULL)."""

    __tablename__ = "profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        db.ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=True
    )
    display_name: Mapped[str] = mapped_column(db.String(80), nullable=False)
    birth_date: Mapped[date | None] = mapped_column(db.Date, nullable=True)
    color: Mapped[str] = mapped_column(db.String(7), default="#4f46e5", nullable=False)
    avatar_filename: Mapped[str | None] = mapped_column(db.String(255), nullable=True)
    bio: Mapped[str | None] = mapped_column(db.String(500), nullable=True)

    user: Mapped["User | None"] = relationship(back_populates="profile")  # noqa: F821
    memberships: Mapped[list["FamilyMember"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def is_dependent(self) -> bool:
        return self.user_id is None

    @property
    def initials(self) -> str:
        parts = [p for p in self.display_name.split() if p]
        letters = "".join(p[0] for p in parts[:2]) or "?"
        return letters.upper()

    def __repr__(self) -> str:
        return f"<Profile {self.id} {self.display_name}>"


class FamilyMember(db.Model):
    __tablename__ = "family_members"
    __table_args__ = (
        db.UniqueConstraint("family_id", "profile_id"),
        db.CheckConstraint("role IN ('admin','member','dependent')", name="role_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    family_id: Mapped[int] = mapped_column(
        db.ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True
    )
    profile_id: Mapped[int] = mapped_column(
        db.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(db.String(16), nullable=False, default=ROLE_MEMBER)
    joined_at: Mapped[datetime] = mapped_column(db.DateTime, default=utcnow, nullable=False)

    family: Mapped[Family] = relationship(back_populates="memberships")
    profile: Mapped[Profile] = relationship(back_populates="memberships")

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN

    @property
    def role_label(self) -> str:
        return ROLE_LABELS.get(self.role, self.role)


class FamilyInvitation(db.Model):
    __tablename__ = "family_invitations"
    __table_args__ = (
        db.CheckConstraint("role IN ('admin','member')", name="role_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    family_id: Mapped[int] = mapped_column(
        db.ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code_hash: Mapped[str] = mapped_column(db.String(64), unique=True, nullable=False)
    role: Mapped[str] = mapped_column(db.String(16), nullable=False, default=ROLE_MEMBER)
    note: Mapped[str | None] = mapped_column(db.String(120), nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(db.DateTime, default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(db.DateTime, nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(db.DateTime, nullable=True)
    accepted_by_user_id: Mapped[int | None] = mapped_column(
        db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(db.DateTime, nullable=True)

    family: Mapped[Family] = relationship(back_populates="invitations")
    created_by: Mapped["User | None"] = relationship(foreign_keys=[created_by_user_id])  # noqa: F821
    accepted_by: Mapped["User | None"] = relationship(foreign_keys=[accepted_by_user_id])  # noqa: F821

    @property
    def status(self) -> str:
        if self.revoked_at:
            return "revoked"
        if self.accepted_at:
            return "accepted"
        if self.expires_at <= utcnow():
            return "expired"
        return "pending"

    @property
    def status_label(self) -> str:
        return {
            "revoked": "Revocato",
            "accepted": "Utilizzato",
            "expired": "Scaduto",
            "pending": "Attivo",
        }[self.status]

    @property
    def role_label(self) -> str:
        return ROLE_LABELS.get(self.role, self.role)
