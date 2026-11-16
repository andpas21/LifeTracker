"""Colonne comuni riutilizzate da più modelli."""
from datetime import datetime

from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.utils.timezone import utcnow


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(db.DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)
