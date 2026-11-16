"""Registrazioni delle attività ("+1"), valori degli indicatori, allegati e storico."""
from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.mixins import TimestampMixin
from app.utils.timezone import utcnow

VISIBILITY_PRIVATE = "private"
VISIBILITY_FAMILY = "family"
VISIBILITY_LABELS = {VISIBILITY_PRIVATE: "Solo io e chi l'ha svolta", VISIBILITY_FAMILY: "Tutta la famiglia"}

entry_tags = db.Table(
    "entry_tags",
    db.Column("entry_id", db.ForeignKey("activity_entries.id", ondelete="CASCADE"), primary_key=True),
    db.Column("tag_id", db.ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True, index=True),
)

entry_participants = db.Table(
    "entry_participants",
    db.Column("entry_id", db.ForeignKey("activity_entries.id", ondelete="CASCADE"), primary_key=True),
    db.Column("profile_id", db.ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True, index=True),
)


class ActivityEntry(TimestampMixin, db.Model):
    __tablename__ = "activity_entries"
    __table_args__ = (
        db.Index("ix_activity_entries_family_occurred", "family_id", "occurred_at"),
        db.CheckConstraint("scope IN ('personal','family')", name="scope_valid"),
        db.CheckConstraint("visibility IN ('private','family')", name="visibility_valid"),
        db.CheckConstraint("quantity > 0", name="quantity_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    family_id: Mapped[int] = mapped_column(db.ForeignKey("families.id", ondelete="CASCADE"), nullable=False)
    activity_id: Mapped[int] = mapped_column(db.ForeignKey("activities.id"), nullable=False, index=True)
    performed_by_profile_id: Mapped[int] = mapped_column(db.ForeignKey("profiles.id"), nullable=False, index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    occurred_at: Mapped[datetime] = mapped_column(db.DateTime, nullable=False, default=utcnow)
    quantity: Mapped[Decimal] = mapped_column(db.Numeric(14, 4), nullable=False, default=1)
    scope: Mapped[str] = mapped_column(db.String(10), nullable=False, default="personal")
    visibility: Mapped[str] = mapped_column(db.String(10), nullable=False, default=VISIBILITY_FAMILY)
    description: Mapped[str | None] = mapped_column(db.String(500), nullable=True)
    notes: Mapped[str | None] = mapped_column(db.Text, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(db.DateTime, nullable=True, index=True)

    activity: Mapped["Activity"] = relationship()  # noqa: F821
    performed_by: Mapped["Profile"] = relationship(foreign_keys=[performed_by_profile_id])  # noqa: F821
    created_by: Mapped["User | None"] = relationship(foreign_keys=[created_by_user_id])  # noqa: F821
    metric_values: Mapped[list["MetricValue"]] = relationship(
        back_populates="entry", cascade="all, delete-orphan", passive_deletes=True
    )
    tags: Mapped[list["Tag"]] = relationship(secondary=entry_tags, order_by="Tag.name")  # noqa: F821
    participants: Mapped[list["Profile"]] = relationship(  # noqa: F821
        secondary=entry_participants, order_by="Profile.display_name"
    )
    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="entry", cascade="all, delete-orphan", passive_deletes=True, order_by="Attachment.id"
    )
    revisions: Mapped[list["EntryRevision"]] = relationship(
        back_populates="entry",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="EntryRevision.changed_at.desc(), EntryRevision.id.desc()",
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def value_for(self, metric_id: int):
        for value in self.metric_values:
            if value.metric_definition_id == metric_id:
                return value
        return None


class MetricValue(db.Model):
    __tablename__ = "metric_values"
    __table_args__ = (db.UniqueConstraint("entry_id", "metric_definition_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(
        db.ForeignKey("activity_entries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    metric_definition_id: Mapped[int] = mapped_column(
        db.ForeignKey("metric_definitions.id"), nullable=False, index=True
    )
    value_numeric: Mapped[Decimal | None] = mapped_column(db.Numeric(14, 4), nullable=True)
    value_text: Mapped[str | None] = mapped_column(db.String(500), nullable=True)

    entry: Mapped[ActivityEntry] = relationship(back_populates="metric_values")
    definition: Mapped["MetricDefinition"] = relationship()  # noqa: F821


class Attachment(db.Model):
    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    family_id: Mapped[int] = mapped_column(
        db.ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entry_id: Mapped[int] = mapped_column(
        db.ForeignKey("activity_entries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stored_filename: Mapped[str] = mapped_column(db.String(255), nullable=False, unique=True)
    original_filename: Mapped[str] = mapped_column(db.String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(db.String(80), nullable=False)
    size_bytes: Mapped[int] = mapped_column(db.Integer, nullable=False)
    uploaded_by_user_id: Mapped[int | None] = mapped_column(
        db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(db.DateTime, default=utcnow, nullable=False)

    entry: Mapped[ActivityEntry] = relationship(back_populates="attachments")

    @property
    def is_image(self) -> bool:
        return self.mime_type.startswith("image/")


class EntryRevision(db.Model):
    """Fotografia dello stato della registrazione dopo ogni modifica (storico)."""

    __tablename__ = "entry_revisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(
        db.ForeignKey("activity_entries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    changed_by_user_id: Mapped[int | None] = mapped_column(
        db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    changed_at: Mapped[datetime] = mapped_column(db.DateTime, default=utcnow, nullable=False)
    action: Mapped[str] = mapped_column(db.String(10), nullable=False)
    snapshot_json: Mapped[str] = mapped_column("snapshot", db.Text, nullable=False)

    entry: Mapped[ActivityEntry] = relationship(back_populates="revisions")
    changed_by: Mapped["User | None"] = relationship()  # noqa: F821

    @property
    def snapshot(self) -> dict:
        return json.loads(self.snapshot_json)
