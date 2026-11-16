"""Gestione di date e orari.

Regola d'oro: nel database salviamo sempre datetime *naive in UTC*.
La conversione al fuso locale (Europe/Rome di default) avviene solo
- quando mostriamo una data all'utente (filtro Jinja `localdt`),
- quando leggiamo una data inserita in un form (to_utc).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from flask import current_app, has_app_context

DEFAULT_TZ = "Europe/Rome"


def app_tz() -> ZoneInfo:
    name = current_app.config.get("APP_TIMEZONE", DEFAULT_TZ) if has_app_context() else DEFAULT_TZ
    return ZoneInfo(name)


def utcnow() -> datetime:
    """Ora attuale in UTC, naive (formato usato nel DB)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_local(value: datetime | None, tz: ZoneInfo | None = None) -> datetime | None:
    """Converte un datetime UTC naive del DB nel fuso locale (aware)."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(tz or app_tz())


def to_utc(value: datetime, tz: ZoneInfo | None = None) -> datetime:
    """Converte un datetime locale (naive = ora locale, o aware) in UTC naive."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=tz or app_tz())
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def local_now(tz: ZoneInfo | None = None) -> datetime:
    return datetime.now(tz or app_tz())


def local_today(tz: ZoneInfo | None = None) -> date:
    return local_now(tz).date()


def format_local(value: datetime | None, fmt: str = "%d/%m/%Y %H:%M") -> str:
    local = to_local(value)
    return local.strftime(fmt) if local else ""
