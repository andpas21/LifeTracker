from datetime import timedelta

from app.extensions import db
from app.models import AuditLog, User
from app.utils.timezone import utcnow
from tests.conftest import PASSWORD


def test_register_creates_user_and_profile(client):
    resp = client.post(
        "/registrati",
        data={"display_name": "Marco", "email": "Marco@Famiglia.it ", "password": PASSWORD, "confirm": PASSWORD},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "Benvenuto in LifeTracker" in resp.get_data(as_text=True)
    user = db.session.scalar(db.select(User).filter_by(email="marco@famiglia.it"))
    assert user is not None
    assert user.profile.display_name == "Marco"
    assert user.password_hash != PASSWORD and user.password_hash.startswith("scrypt")


def test_register_rejects_duplicate_email(client, make_user):
    make_user()
    resp = client.post(
        "/registrati",
        data={"display_name": "Altro", "email": "anna@famiglia.it", "password": PASSWORD, "confirm": PASSWORD},
        follow_redirects=True,
    )
    assert "Esiste già un account" in resp.get_data(as_text=True)
    assert db.session.scalar(db.select(db.func.count()).select_from(User)) == 1


def test_register_rejects_weak_password(client):
    resp = client.post(
        "/registrati",
        data={"display_name": "Marco", "email": "m@famiglia.it", "password": "soloLettere", "confirm": "soloLettere"},
        follow_redirects=True,
    )
    assert "lettere sia numeri" in resp.get_data(as_text=True)
    assert db.session.scalar(db.select(User).filter_by(email="m@famiglia.it")) is None


def test_registration_closed_requires_invite(app, client):
    app.config["ALLOW_REGISTRATION"] = False
    resp = client.post(
        "/registrati",
        data={"display_name": "Marco", "email": "m@famiglia.it", "password": PASSWORD, "confirm": PASSWORD},
    )
    assert "solo con un codice" in resp.get_data(as_text=True)
    assert db.session.scalar(db.select(User).filter_by(email="m@famiglia.it")) is None


def test_login_and_logout(client, make_user, login):
    make_user()
    resp = login()
    assert "Benvenuto in LifeTracker" in resp.get_data(as_text=True)  # nessuna famiglia → onboarding
    resp = client.post("/esci", follow_redirects=True)
    assert "Sei uscito" in resp.get_data(as_text=True)
    assert client.get("/famiglia/").status_code == 302


def test_login_wrong_password_and_lockout(app, client, make_user, login):
    user = make_user()
    for _ in range(app.config["LOGIN_MAX_ATTEMPTS"]):
        resp = login(password="sbagliata-123")
        assert "Email o password non corretti" in resp.get_data(as_text=True)
    db.session.refresh(user)
    assert user.locked_until is not None and user.locked_until > utcnow()
    # anche con la password giusta l'account resta bloccato
    resp = login()
    assert "Troppi tentativi" in resp.get_data(as_text=True)
    # scaduto il blocco si entra di nuovo
    user.locked_until = utcnow() - timedelta(minutes=1)
    db.session.commit()
    resp = login()
    assert "Benvenuto in LifeTracker" in resp.get_data(as_text=True)
    actions = [a.action for a in db.session.scalars(db.select(AuditLog))]
    assert "auth.locked" in actions and "auth.login" in actions


def test_login_unknown_email_generic_error(client, login):
    resp = login(email="nessuno@famiglia.it")
    assert "Email o password non corretti" in resp.get_data(as_text=True)


def test_open_redirect_blocked(client, make_user):
    make_user()
    resp = client.post(
        "/accedi?next=https://evil.example.com/", data={"email": "anna@famiglia.it", "password": PASSWORD}
    )
    assert resp.status_code == 302
    assert "evil" not in resp.headers["Location"]


def test_protected_pages_require_login(client):
    for url in ("/", "/famiglia/", "/profilo/", "/famiglia/inviti", "/profilo/password"):
        resp = client.get(url)
        assert resp.status_code == 302
        assert "/accedi" in resp.headers["Location"]


def test_change_password(client, make_user, login):
    user = make_user()
    login()
    resp = client.post(
        "/profilo/password",
        data={"current_password": "sbagliata", "new_password": "NuovaPass-456", "confirm": "NuovaPass-456"},
        follow_redirects=True,
    )
    assert "La password attuale non è corretta" in resp.get_data(as_text=True)
    resp = client.post(
        "/profilo/password",
        data={"current_password": PASSWORD, "new_password": "NuovaPass-456", "confirm": "NuovaPass-456"},
        follow_redirects=True,
    )
    assert "Password aggiornata" in resp.get_data(as_text=True)
    db.session.refresh(user)
    assert user.check_password("NuovaPass-456")
