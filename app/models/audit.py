"""Registro delle azioni (audit log)."""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.utils.timezone import utcnow


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    family_id: Mapped[int | None] = mapped_column(
        db.ForeignKey("families.id", ondelete="CASCADE"), nullable=True, index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(db.String(40), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(db.String(40), nullable=True)
    entity_id: Mapped[int | None] = mapped_column(db.Integer, nullable=True)
    details_json: Mapped[str | None] = mapped_column("details", db.Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(db.String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(db.DateTime, default=utcnow, nullable=False, index=True)

    user: Mapped["User | None"] = relationship()  # noqa: F821

    @property
    def details(self) -> dict:
        return json.loads(self.details_json) if self.details_json else {}
