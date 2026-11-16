"""Account utente (credenziali di accesso)."""
from __future__ import annotations

from datetime import datetime

from flask_login import UserMixin
from sqlalchemy.orm import Mapped, mapped_column, relationship
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.models.mixins import TimestampMixin

THEMES = ("auto", "light", "dark")


class User(UserMixin, TimestampMixin, db.Model):
    __tablename__ = "users"
    __table_args__ = (
        db.CheckConstraint("theme IN ('auto','light','dark')", name="theme_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(db.String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(db.String(255), nullable=False)
    is_active_account: Mapped[bool] = mapped_column("is_active", db.Boolean, default=True, nullable=False)
    current_family_id: Mapped[int | None] = mapped_column(
        db.ForeignKey("families.id", ondelete="SET NULL", use_alter=True), nullable=True
    )
    theme: Mapped[str] = mapped_column(db.String(10), default="auto", nullable=False)
    failed_login_count: Mapped[int] = mapped_column(db.Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(db.DateTime, nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(db.DateTime, nullable=True)
    # Preferenze personali
    weekly_summary: Mapped[bool] = mapped_column(db.Boolean, default=True, nullable=False)
    monthly_summary: Mapped[bool] = mapped_column(db.Boolean, default=True, nullable=False)
    goal_notifications: Mapped[bool] = mapped_column(db.Boolean, default=True, nullable=False)

    profile: Mapped["Profile"] = relationship(  # noqa: F821
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    current_family: Mapped["Family | None"] = relationship(foreign_keys=[current_family_id])  # noqa: F821

    # --- Password -----------------------------------------------------------
    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    # --- Flask-Login ----------------------------------------------------------
    @property
    def is_active(self) -> bool:  # usato da Flask-Login per bloccare account disattivati
        return self.is_active_account

    @property
    def display_name(self) -> str:
        return self.profile.display_name if self.profile else self.email

    def __repr__(self) -> str:
        return f"<User {self.id} {self.email}>"
