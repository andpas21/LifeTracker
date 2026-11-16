"""Comandi da riga di comando:  flask lt <comando>

Utili per l'amministrazione del server (es. sul Raspberry Pi), dove non c'è
un servizio email per il recupero password.
"""
import click
from flask import Flask

from app.extensions import db


def register_cli(app: Flask) -> None:
    @app.cli.group("lt")
    def lt():
        """Comandi di amministrazione LifeTracker."""

    @lt.command("reset-password")
    @click.argument("email")
    @click.password_option("--password", prompt="Nuova password")
    def reset_password(email, password):
        """Reimposta la password di un utente."""
        from app.models import User
        from app.services import ServiceError
        from app.services.audit_service import log_action
        from app.services.auth_service import normalize_email, validate_password_strength

        user = db.session.scalar(db.select(User).filter_by(email=normalize_email(email)))
        if user is None:
            raise click.ClickException("Utente non trovato.")
        try:
            validate_password_strength(password)
        except ServiceError as exc:
            raise click.ClickException(str(exc)) from exc
        user.set_password(password)
        user.failed_login_count = 0
        user.locked_until = None
        log_action("auth.password_reset_cli", entity=user, user_id=user.id)
        db.session.commit()
        click.echo(f"Password aggiornata per {user.email}.")

    @lt.command("unlock")
    @click.argument("email")
    def unlock(email):
        """Sblocca un account bloccato per troppi tentativi di accesso."""
        from app.models import User
        from app.services.auth_service import normalize_email

        user = db.session.scalar(db.select(User).filter_by(email=normalize_email(email)))
        if user is None:
            raise click.ClickException("Utente non trovato.")
        user.failed_login_count = 0
        user.locked_until = None
        db.session.commit()
        click.echo(f"Account {user.email} sbloccato.")

    @lt.command("users")
    def list_users():
        """Elenca gli account registrati."""
        from app.models import User

        for user in db.session.scalars(db.select(User).order_by(User.id)):
            stato = "attivo" if user.is_active_account else "disattivato"
            click.echo(f"{user.id:>4}  {user.email:<40} {user.display_name:<25} {stato}")
