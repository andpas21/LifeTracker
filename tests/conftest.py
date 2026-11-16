"""Fixture condivise dai test (pytest).

Ogni test riceve un'app nuova con database SQLite in memoria e cartella
instance temporanea: i test sono indipendenti tra loro.
"""
import re

import pytest

from app import create_app
from app.extensions import db as _db
from app.services import auth_service, family_service

PASSWORD = "Password-123"


@pytest.fixture()
def app(tmp_path):
    app = create_app("testing")
    app.config["UPLOAD_FOLDER"] = str(tmp_path / "uploads")
    with app.app_context():
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def make_user(app):
    def _make(email="anna@famiglia.it", name="Anna Rossi", password=PASSWORD):
        return auth_service.register_user(email, password, name)

    return _make


@pytest.fixture()
def login(client):
    def _login(email="anna@famiglia.it", password=PASSWORD):
        return client.post("/accedi", data={"email": email, "password": password}, follow_redirects=True)

    return _login


@pytest.fixture()
def family_with_admin(make_user):
    """Utente admin 'Anna' con famiglia 'Rossi'. Restituisce (user, family)."""
    user = make_user()
    family = family_service.create_family(user, "Famiglia Rossi")
    return user, family


def extract_invite_code(html: str) -> str:
    match = re.search(r'id="ltInviteCode">([A-Z0-9-]+)<', html)
    assert match, "codice invito non trovato nella pagina"
    return match.group(1)
