"""Istanze delle estensioni Flask, create qui e inizializzate in create_app().

Tenerle in un modulo separato evita import circolari: i modelli importano `db`
da qui, non dall'app.
"""
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import MetaData, event
from sqlalchemy.engine import Engine

# Nomi espliciti per vincoli e indici: necessari ad Alembic per poter
# modificare/eliminare i vincoli (soprattutto con SQLite in "batch mode").
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

db = SQLAlchemy(metadata=MetaData(naming_convention=NAMING_CONVENTION))
migrate = Migrate()
csrf = CSRFProtect()
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Accedi per continuare."
login_manager.login_message_category = "info"
login_manager.session_protection = "strong"


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_connection, connection_record):  # pragma: no cover - dipende dal driver
    """SQLite non applica le chiavi esterne se non lo si chiede esplicitamente."""
    module = type(dbapi_connection).__module__
    if module.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()
