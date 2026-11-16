"""Registrazione, autenticazione e gestione password."""
from __future__ import annotations

from datetime import timedelta

from flask import current_app

from app.extensions import db
from app.models import Profile, User
from app.services import ServiceError
from app.services.audit_service import log_action
from app.utils.timezone import utcnow

MIN_PASSWORD_LENGTH = 10


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def validate_password_strength(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ServiceError(f"La password deve contenere almeno {MIN_PASSWORD_LENGTH} caratteri.")
    if password.isdigit() or password.isalpha():
        raise ServiceError("La password deve contenere sia lettere sia numeri o simboli.")


def register_user(email: str, password: str, display_name: str) -> User:
    email = normalize_email(email)
    if db.session.scalar(db.select(User).filter_by(email=email)):
        raise ServiceError("Esiste già un account con questa email.")
    validate_password_strength(password)
    user = User(email=email)
    user.set_password(password)
    user.profile = Profile(display_name=display_name.strip())
    db.session.add(user)
    db.session.flush()
    log_action("auth.register", entity=user, user_id=user.id)
    db.session.commit()
    current_app.logger.info("Nuovo utente registrato: id=%s", user.id)
    return user


def authenticate(email: str, password: str) -> User:
    """Verifica le credenziali applicando il blocco temporaneo dopo troppi tentativi."""
    generic_error = ServiceError("Email o password non corretti.")
    user = db.session.scalar(db.select(User).filter_by(email=normalize_email(email)))
    if user is None:
        # Calcola comunque un hash per non rivelare (dai tempi di risposta) se l'email esiste.
        User(email="", password_hash="").set_password(password or "x")
        raise generic_error

    now = utcnow()
    if user.locked_until and user.locked_until > now:
        minutes = int((user.locked_until - now).total_seconds() // 60) + 1
        raise ServiceError(f"Troppi tentativi falliti. Riprova tra {minutes} minuti.")
    if not user.is_active_account:
        raise ServiceError("Questo account è disattivato.")

    if not user.check_password(password):
        user.failed_login_count += 1
        max_attempts = current_app.config["LOGIN_MAX_ATTEMPTS"]
        if user.failed_login_count >= max_attempts:
            user.locked_until = now + timedelta(minutes=current_app.config["LOGIN_LOCK_MINUTES"])
            user.failed_login_count = 0
            log_action("auth.locked", entity=user, user_id=user.id)
            current_app.logger.warning("Account bloccato per tentativi falliti: id=%s", user.id)
        else:
            log_action("auth.login_failed", entity=user, user_id=user.id)
        db.session.commit()
        raise generic_error

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    log_action("auth.login", entity=user, user_id=user.id, family_id=user.current_family_id)
    db.session.commit()
    return user


def change_password(user: User, current_password: str, new_password: str) -> None:
    if not user.check_password(current_password):
        raise ServiceError("La password attuale non è corretta.")
    if current_password == new_password:
        raise ServiceError("La nuova password deve essere diversa da quella attuale.")
    validate_password_strength(new_password)
    user.set_password(new_password)
    log_action("auth.password_changed", entity=user, user_id=user.id)
    db.session.commit()


def set_theme(user: User, theme: str) -> None:
    from app.models import THEMES

    if theme not in THEMES:
        raise ServiceError("Tema non valido.")
    user.theme = theme
    db.session.commit()
