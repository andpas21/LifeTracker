"""Configurazione dell'applicazione.

Tutti i valori sensibili o dipendenti dall'installazione arrivano da variabili
d'ambiente (o dal file .env, caricato in create_app). Così lo stesso codice gira
in sviluppo, nei test e sul Raspberry Pi senza modifiche.
"""
import os
from datetime import timedelta


def _bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "si", "sì"}


class BaseConfig:
    SECRET_KEY = os.environ.get("SECRET_KEY")

    # --- Database -----------------------------------------------------------
    # Se DATABASE_URL è vuota si usa SQLite nella cartella instance/ (vedi create_app).
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or None
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    # --- Sessioni e cookie --------------------------------------------------
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE")
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE")
    REMEMBER_COOKIE_DURATION = timedelta(days=30)
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)

    # --- CSRF ---------------------------------------------------------------
    WTF_CSRF_TIME_LIMIT = None  # il token vale per tutta la sessione

    # --- Applicazione -------------------------------------------------------
    APP_NAME = "LifeTracker"
    APP_TIMEZONE = os.environ.get("APP_TIMEZONE", "Europe/Rome")
    ALLOW_REGISTRATION = _bool("ALLOW_REGISTRATION", True)
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_UPLOAD_MB", "10")) * 1024 * 1024
    AVATAR_SIZE = 512  # lato massimo in pixel delle foto profilo
    LOGIN_MAX_ATTEMPTS = 5
    LOGIN_LOCK_MINUTES = 15
    INVITATION_DEFAULT_DAYS = 7
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

    # Cartelle (relative a instance_path se non assolute)
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", "uploads")
    LOG_FOLDER = os.environ.get("LOG_FOLDER", "logs")


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    SECRET_KEY = BaseConfig.SECRET_KEY or "dev-only-insecure-key"


class TestingConfig(BaseConfig):
    TESTING = True
    SECRET_KEY = "test-secret-key"
    SQLALCHEMY_DATABASE_URI = "sqlite://"  # database in memoria
    WTF_CSRF_ENABLED = False  # i test CSRF lo riattivano esplicitamente
    LOG_LEVEL = "WARNING"


class ProductionConfig(BaseConfig):
    DEBUG = False


CONFIGS = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}
