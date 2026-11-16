"""Catalogo personalizzabile della famiglia: categorie, attività, indicatori, tag."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.mixins import TimestampMixin

# --------------------------------------------------------------------------- costanti
SCOPE_PERSONAL = "personal"
SCOPE_FAMILY = "family"
SCOPE_LABELS = {SCOPE_PERSONAL: "Personale", SCOPE_FAMILY: "Familiare"}

DATA_TYPE_LABELS = {
    "integer": "Numero intero",
    "decimal": "Numero decimale",
    "duration": "Durata (ore:minuti)",
    "boolean": "Sì / No",
    "text": "Testo",
}
NUMERIC_TYPES = ("integer", "decimal", "duration", "boolean")

# Significato dell'indicatore: permette confronti omogenei tra attività diverse.
KIND_LABELS = {
    "count": "Conteggio",
    "distance": "Distanza",
    "duration": "Durata",
    "elevation": "Dislivello",
    "heart_rate": "Frequenza cardiaca",
    "power": "Potenza",
    "speed": "Velocità",
    "weight": "Peso",
    "energy": "Energia / calorie",
    "money": "Denaro",
    "people": "Persone",
    "other": "Altro",
}

AGGREGATION_LABELS = {"sum": "Somma", "avg": "Media", "max": "Massimo", "min": "Minimo"}


class Category(TimestampMixin, db.Model):
    __tablename__ = "categories"
    __table_args__ = (db.UniqueConstraint("family_id", "parent_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    family_id: Mapped[int] = mapped_column(
        db.ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_id: Mapped[int | None] = mapped_column(
        db.ForeignKey("categories.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(db.String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(db.String(500), nullable=True)
    icon: Mapped[str] = mapped_column(db.String(64), default="tag", nullable=False)
    color: Mapped[str] = mapped_column(db.String(7), default="#4f46e5", nullable=False)
    sort_order: Mapped[int] = mapped_column(db.Integer, default=0, nullable=False)
    is_archived: Mapped[bool] = mapped_column(db.Boolean, default=False, nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(
        db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    parent: Mapped["Category | None"] = relationship(remote_side=[id], back_populates="children")
    children: Mapped[list["Category"]] = relationship(
        back_populates="parent", order_by="Category.sort_order, Category.name"
    )
    activities: Mapped[list["Activity"]] = relationship(
        back_populates="category", order_by="Activity.sort_order, Activity.name"
    )

    @property
    def full_name(self) -> str:
        return f"{self.parent.name} › {self.name}" if self.parent else self.name


class Activity(TimestampMixin, db.Model):
    __tablename__ = "activities"
    __table_args__ = (
        db.UniqueConstraint("family_id", "name"),
        db.CheckConstraint("default_scope IN ('personal','family')", name="scope_valid"),
        db.CheckConstraint("default_quantity > 0", name="quantity_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    family_id: Mapped[int] = mapped_column(
        db.ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category_id: Mapped[int] = mapped_column(db.ForeignKey("categories.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(db.String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(db.String(500), nullable=True)
    icon: Mapped[str | None] = mapped_column(db.String(64), nullable=True)
    color: Mapped[str | None] = mapped_column(db.String(7), nullable=True)
    count_label: Mapped[str] = mapped_column(db.String(40), default="volte", nullable=False)
    default_quantity: Mapped[Decimal] = mapped_column(db.Numeric(14, 4), default=1, nullable=False)
    default_scope: Mapped[str] = mapped_column(db.String(10), default=SCOPE_PERSONAL, nullable=False)
    is_quick: Mapped[bool] = mapped_column(db.Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(db.Integer, default=0, nullable=False)
    is_archived: Mapped[bool] = mapped_column(db.Boolean, default=False, nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(
        db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    category: Mapped[Category] = relationship(back_populates="activities")
    metrics: Mapped[list["MetricDefinition"]] = relationship(
        back_populates="activity",
        order_by="MetricDefinition.sort_order, MetricDefinition.id",
        cascade="all, delete-orphan",
    )

    @property
    def display_icon(self) -> str:
        return self.icon or self.category.icon

    @property
    def display_color(self) -> str:
        return self.color or self.category.color

    @property
    def active_metrics(self) -> list["MetricDefinition"]:
        return [m for m in self.metrics if not m.is_archived]


class MetricDefinition(db.Model):
    __tablename__ = "metric_definitions"
    __table_args__ = (
        db.UniqueConstraint("activity_id", "key"),
        db.CheckConstraint(
            "data_type IN ('integer','decimal','duration','boolean','text')", name="data_type_valid"
        ),
        db.CheckConstraint("aggregation IN ('sum','avg','max','min')", name="aggregation_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    activity_id: Mapped[int] = mapped_column(
        db.ForeignKey("activities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(db.String(60), nullable=False)
    key: Mapped[str] = mapped_column(db.String(40), nullable=False)
    data_type: Mapped[str] = mapped_column(db.String(16), nullable=False, default="decimal")
    unit: Mapped[str | None] = mapped_column(db.String(20), nullable=True)
    kind: Mapped[str] = mapped_column(db.String(20), nullable=False, default="other")
    aggregation: Mapped[str] = mapped_column(db.String(8), nullable=False, default="sum")
    min_value: Mapped[Decimal | None] = mapped_column(db.Numeric(14, 4), nullable=True)
    max_value: Mapped[Decimal | None] = mapped_column(db.Numeric(14, 4), nullable=True)
    is_required: Mapped[bool] = mapped_column(db.Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(db.Integer, default=0, nullable=False)
    is_archived: Mapped[bool] = mapped_column(db.Boolean, default=False, nullable=False)

    activity: Mapped[Activity] = relationship(back_populates="metrics")

    @property
    def is_numeric(self) -> bool:
        return self.data_type in NUMERIC_TYPES

    @property
    def display_unit(self) -> str:
        if self.data_type == "duration":
            return "h"
        return self.unit or ""

    @property
    def label(self) -> str:
        unit = self.display_unit
        return f"{self.name} ({unit})" if unit else self.name


class Tag(db.Model):
    __tablename__ = "tags"
    __table_args__ = (db.UniqueConstraint("family_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    family_id: Mapped[int] = mapped_column(
        db.ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(db.String(40), nullable=False)
    color: Mapped[str] = mapped_column(db.String(7), default="#64748b", nullable=False)
