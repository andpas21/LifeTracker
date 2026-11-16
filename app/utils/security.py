"""Decoratori e helper per autenticazione, famiglia attiva e permessi."""
from __future__ import annotations

from functools import wraps
from urllib.parse import urlsplit

from flask import abort, flash, redirect, request, url_for
from flask_login import current_user, login_required


def client_ip() -> str | None:
    # Dietro Nginx l'IP reale arriva da X-Forwarded-For (gestito da ProxyFix in create_app).
    return request.remote_addr


def is_safe_next_url(target: str | None) -> bool:
    """Evita open redirect: accetta solo percorsi relativi dello stesso sito."""
    if not target:
        return False
    parts = urlsplit(target)
    return not parts.scheme and not parts.netloc and target.startswith("/") and not target.startswith("//")


def get_current_membership():
    """FamilyMember dell'utente loggato nella famiglia attiva (o None).

    Il risultato è memorizzato sull'oggetto `request`, quindi vale per una sola richiesta.
    """
    if not current_user.is_authenticated:
        return None
    if not hasattr(request, "_lt_membership"):
        from app.services import family_service

        request._lt_membership = family_service.resolve_current_membership(current_user)
    return request._lt_membership


def get_current_family():
    membership = get_current_membership()
    return membership.family if membership else None


def family_required(view):
    """Richiede login e una famiglia attiva; altrimenti porta alla pagina di benvenuto."""

    @wraps(view)
    @login_required
    def wrapper(*args, **kwargs):
        if get_current_membership() is None:
            flash("Crea una famiglia o unisciti a una famiglia esistente per continuare.", "info")
            return redirect(url_for("family.welcome"))
        return view(*args, **kwargs)

    return wrapper


def family_admin_required(view):
    """Come family_required, ma solo per gli amministratori della famiglia attiva."""

    @wraps(view)
    @family_required
    def wrapper(*args, **kwargs):
        if not get_current_membership().is_admin:
            abort(403)
        return view(*args, **kwargs)

    return wrapper
