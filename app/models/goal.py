"""Obiettivi, storico degli obiettivi, promemoria e notifiche."""
from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.mixins import TimestampMixin
from app.utils.timezone import utcnow

GOAL_TARGET_LABELS = {
    "count": "Numero di registrazioni",
    "quantity": "Quantità (es. uscite, sessioni)",
    "metric": "Valore di un indicatore",
}
GOAL_RECURRENCE_LABELS = {
    "none": "Una tantum (dall'inizio alla scadenza)",
    "weekly": "Ogni settimana",
    "monthly": "Ogni mese",
    "yearly": "Ogni anno",
}
GOAL_STATUS_LABELS = {
    "active": "In corso",
    "completed": "Raggiunto",
    "expired": "Scaduto",
    "archived": "Archiviato",
}


class Goal(TimestampMixin, db.Model):
    __tablename__ = "goals"
    __table_args__ = (
        db.CheckConstraint("target_type IN ('count','quantity','metric')", name="target_type_valid"),
        db.CheckConstraint("recurrence IN ('none','weekly','monthly','yearly')", name="recurrence_valid"),
        db.CheckConstraint("status IN ('active','completed','expired','archived')", name="status_valid"),
        db.CheckConstraint("scope IN ('personal','family')", name="scope_valid"),
        db.CheckConstraint("visibility IN ('private','family')", name="visibility_valid"),
        db.CheckConstraint("target_value > 0", name="target_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    family_id: Mapped[int] = mapped_column(
        db.ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_profile_id: Mapped[int | None] = mapped_column(
        db.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=True, index=True
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    scope: Mapped[str] = mapped_column(db.String(10), nullable=False, default="personal")
    visibility: Mapped[str] = mapped_column(db.String(10), nullable=False, default="family")
    title: Mapped[str] = mapped_column(db.String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(db.String(500), nullable=True)
    target_type: Mapped[str] = mapped_column(db.String(10), nullable=False, default="count")
    category_id: Mapped[int | None] = mapped_column(
        db.ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )
    activity_id: Mapped[int | None] = mapped_column(
        db.ForeignKey("activities.id", ondelete="SET NULL"), nullable=True
    )
    metric_definition_id: Mapped[int | None] = mapped_column(
        db.ForeignKey("metric_definitions.id", ondelete="SET NULL"), nullable=True
    )
    target_value: Mapped[Decimal] = mapped_column(db.Numeric(14, 4), nullable=False)
    recurrence: Mapped[str] = mapped_column(db.String(10), nullable=False, default="none")
    start_date: Mapped[date] = mapped_column(db.Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(db.Date, nullable=True)
    status: Mapped[str] = mapped_column(db.String(10), nullable=False, default="active", index=True)
    completed_at: Mapped[datetime | None] = mapped_column(db.DateTime, nullable=True)

    owner: Mapped["Profile | None"] = relationship()  # noqa: F821
    created_by: Mapped["User | None"] = relationship()  # noqa: F821
    category: Mapped["Category | None"] = relationship()  # noqa: F821
    activity: Mapped["Activity | None"] = relationship()  # noqa: F821
    metric: Mapped["MetricDefinition | None"] = relationship()  # noqa: F821
    events: Mapped[list["GoalEvent"]] = relationship(
        back_populates="goal", cascade="all, delete-orphan", passive_deletes=True,
        order_by="GoalEvent.created_at.desc(), GoalEvent.id.desc()",
    )

    @property
    def status_label(self) -> str:
        return GOAL_STATUS_LABELS[self.status]

    @property
    def recurrence_label(self) -> str:
        return GOAL_RECURRENCE_LABELS[self.recurrence]


class GoalEvent(db.Model):
    """Storico: creazione, traguardi intermedi, completamenti, scadenze."""

    __tablename__ = "goal_events"
    __table_args__ = (db.UniqueConstraint("goal_id", "event", "period_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    goal_id: Mapped[int] = mapped_column(db.ForeignKey("goals.id", ondelete="CASCADE"), nullable=False, index=True)
    event: Mapped[str] = mapped_column(db.String(20), nullable=False)
    period_key: Mapped[str] = mapped_column(db.String(20), nullable=False, default="")
    value: Mapped[Decimal | None] = mapped_column(db.Numeric(14, 4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(db.DateTime, default=utcnow, nullable=False)

    goal: Mapped[Goal] = relationship(back_populates="events")


class Reminder(TimestampMixin, db.Model):
    __tablename__ = "reminders"
    __table_args__ = (
        db.CheckConstraint("frequency IN ('once','daily','weekly','monthly')", name="frequency_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    family_id: Mapped[int] = mapped_column(
        db.ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    activity_id: Mapped[int | None] = mapped_column(
        db.ForeignKey("activities.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(db.String(120), nullable=False)
    message: Mapped[str | None] = mapped_column(db.String(500), nullable=True)
    frequency: Mapped[str] = mapped_column(db.String(10), nullable=False, default="daily")
    time_of_day: Mapped[time] = mapped_column(db.Time, nullable=False)
    weekdays: Mapped[str | None] = mapped_column(db.String(20), nullable=True)  # "0,2,4" (0 = lunedì)
    day_of_month: Mapped[int | None] = mapped_column(db.Integer, nullable=True)
    start_date: Mapped[date] = mapped_column(db.Date, nullable=False)
    next_run_at: Mapped[datetime | None] = mapped_column(db.DateTime, nullable=True, index=True)
    last_sent_at: Mapped[datetime | None] = mapped_column(db.DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(db.Boolean, default=True, nullable=False)

    activity: Mapped["Activity | None"] = relationship()  # noqa: F821

    @property
    def weekday_list(self) -> list[int]:
        return [int(x) for x in self.weekdays.split(",") if x != ""] if self.weekdays else []


class Notification(db.Model):
    __tablename__ = "notifications"
    __table_args__ = (db.UniqueConstraint("user_id", "dedupe_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    family_id: Mapped[int | None] = mapped_column(
        db.ForeignKey("families.id", ondelete="CASCADE"), nullable=True, index=True
    )
    type: Mapped[str] = mapped_column(db.String(20), nullable=False)
    title: Mapped[str] = mapped_column(db.String(160), nullable=False)
    body: Mapped[str | None] = mapped_column(db.String(500), nullable=True)
    link: Mapped[str | None] = mapped_column(db.String(255), nullable=True)
    dedupe_key: Mapped[str | None] = mapped_column(db.String(80), nullable=True)
    is_read: Mapped[bool] = mapped_column(db.Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(db.DateTime, default=utcnow, nullable=False, index=True)

    @property
    def icon(self) -> str:
        return {
            "goal": "trophy",
            "reminder": "alarm",
            "summary": "bar-chart-line",
            "family": "people",
        }.get(self.type, "bell")
