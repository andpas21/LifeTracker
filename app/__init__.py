"""Factory dell'applicazione LifeTracker.

`create_app()` costruisce un'istanza Flask configurata. Usare una factory
permette di creare app diverse per sviluppo, test e produzione.
"""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

from dotenv import load_dotenv
from flask import Flask, render_template, request
from werkzeug.middleware.proxy_fix import ProxyFix

from app.config import CONFIGS
from app.extensions import csrf, db, login_manager, migrate


def create_app(config_name: str | None = None) -> Flask:
    load_dotenv()
    config_name = config_name or os.environ.get("FLASK_CONFIG", "production")
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(CONFIGS[config_name])
    os.makedirs(app.instance_path, exist_ok=True)

    if not app.config.get("SECRET_KEY"):
        raise RuntimeError("SECRET_KEY non impostata: definiscila nel file .env (vedi .env.example).")
    if not app.config.get("SQLALCHEMY_DATABASE_URI"):
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(app.instance_path, "lifetracker.db")

    # Dietro Nginx: legge IP reale e schema (http/https) dagli header del proxy.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    _init_logging(app)
    db.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)  # batch: necessario per ALTER TABLE su SQLite
    csrf.init_app(app)
    login_manager.init_app(app)

    from app import models  # noqa: F401  registra i modelli

    @login_manager.user_loader
    def load_user(user_id: str):
        return db.session.get(models.User, int(user_id))

    _register_blueprints(app)
    _register_template_helpers(app)
    _register_error_handlers(app)
    _register_security_headers(app)

    from app.cli import register_cli

    register_cli(app)
    app.logger.info("LifeTracker avviato (config=%s)", config_name)
    return app


def _register_blueprints(app: Flask) -> None:
    from app.blueprints.auth import bp as auth_bp
    from app.blueprints.calendar import bp as calendar_bp
    from app.blueprints.catalog import bp as catalog_bp
    from app.blueprints.dashboard import bp as dashboard_bp
    from app.blueprints.entries import bp as entries_bp
    from app.blueprints.goals import bp as goals_bp
    from app.blueprints.family import bp as family_bp
    from app.blueprints.main import bp as main_bp
    from app.blueprints.profile import bp as profile_bp

    for bp in (main_bp, auth_bp, family_bp, profile_bp, catalog_bp, entries_bp, dashboard_bp, goals_bp, calendar_bp):
        app.register_blueprint(bp)


def _init_logging(app: Flask) -> None:
    level = getattr(logging, app.config["LOG_LEVEL"], logging.INFO)
    app.logger.setLevel(level)
    if app.testing:
        return
    log_dir = app.config["LOG_FOLDER"]
    if not os.path.isabs(log_dir):
        log_dir = os.path.join(app.instance_path, log_dir)
    os.makedirs(log_dir, exist_ok=True)
    handler = RotatingFileHandler(
        os.path.join(log_dir, "lifetracker.log"), maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    handler.setLevel(level)
    if not any(isinstance(h, RotatingFileHandler) for h in app.logger.handlers):
        app.logger.addHandler(handler)


def _register_template_helpers(app: Flask) -> None:
    from app.models import ROLE_LABELS
    from app.services import family_service
    from app.services.audit_service import action_label
    from app.services.entry_service import format_metric_value
    from app.utils.security import get_current_membership
    from app.utils.timezone import format_local

    @app.template_filter("localdt")
    def localdt(value, fmt="%d/%m/%Y %H:%M"):
        return format_local(value, fmt)

    from app.utils.formatting import fmt_duration, fmt_hours, fmt_number

    app.add_template_filter(fmt_number, "num")
    app.add_template_filter(fmt_duration, "duration")
    app.add_template_filter(fmt_hours, "hours")

    @app.template_filter("duration_h")
    def duration_h(hours):
        return fmt_duration(float(hours) * 3600) if hours is not None else ""

    @app.template_filter("dict_without")
    def dict_without(mapping, *keys):
        return {k: v for k, v in mapping.items() if k not in keys}

    @app.template_filter("weekday")
    def weekday(value):
        from app.services.period import WEEKDAYS_IT
        from app.utils.timezone import to_local

        local = to_local(value) if hasattr(value, "hour") else value
        return WEEKDAYS_IT[local.weekday()].capitalize() if local else ""

    @app.template_filter("datefmt")
    def datefmt(value, fmt="%d/%m/%Y"):
        return value.strftime(fmt) if value else ""

    @app.context_processor
    def inject_globals():
        from flask_login import current_user

        membership = get_current_membership() if current_user.is_authenticated else None
        return {
            "app_name": app.config["APP_NAME"],
            "current_membership": membership,
            "current_family": membership.family if membership else None,
            "user_memberships": family_service.memberships_of(current_user)
            if current_user.is_authenticated
            else [],
            "role_labels": ROLE_LABELS,
            "action_label": action_label,
            "format_metric": format_metric_value,
        }


def _register_error_handlers(app: Flask) -> None:
    messages = {
        400: ("Richiesta non valida", "La richiesta non è valida o il modulo è scaduto. Riprova."),
        403: ("Accesso negato", "Non hai i permessi per accedere a questa pagina."),
        404: ("Pagina non trovata", "La pagina richiesta non esiste o non è accessibile."),
        405: ("Metodo non consentito", "Operazione non consentita."),
        413: ("File troppo grande", "Il file supera la dimensione massima consentita."),
        429: ("Troppe richieste", "Hai effettuato troppe richieste. Attendi qualche minuto."),
        500: ("Errore interno", "Si è verificato un errore imprevisto. È stato registrato nei log."),
    }

    def make_handler(code):
        def handler(error):
            if code == 500:
                db.session.rollback()
                app.logger.exception("Errore 500 su %s", request.path)
            title, text = messages[code]
            if request.accept_mimetypes.best == "application/json":
                return {"error": title, "message": text}, code
            return render_template("errors/error.html", code=code, title=title, text=text), code

        return handler

    for code in messages:
        app.register_error_handler(code, make_handler(code))

    from flask_wtf.csrf import CSRFError

    @app.errorhandler(CSRFError)
    def csrf_error(error):
        title = "Sessione scaduta"
        text = "Il modulo è scaduto o non è valido. Ricarica la pagina e riprova."
        return render_template("errors/error.html", code=400, title=title, text=text), 400


def _register_security_headers(app: Flask) -> None:
    csp = (
        "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
        "base-uri 'self'; form-action 'self'; object-src 'none'"
    )

    @app.after_request
    def set_headers(response):
        response.headers.setdefault("Content-Security-Policy", csp)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=(self)")
        return response
