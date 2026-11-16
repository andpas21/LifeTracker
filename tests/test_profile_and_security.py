import io
import os

from PIL import Image

from app.extensions import db
from app.utils.timezone import to_local, to_utc
from app.utils.uploads import upload_dir


def _png_bytes(size=(800, 600), color=(200, 30, 30)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    buf.seek(0)
    return buf


def test_update_profile(client, family_with_admin, login):
    admin, _ = family_with_admin
    login()
    resp = client.post("/profilo/", data={"display_name": "Anna R.", "color": "#0EA5E9", "bio": "Ciao"},
                       follow_redirects=True)
    assert "Profilo aggiornato" in resp.get_data(as_text=True)
    assert admin.profile.display_name == "Anna R."
    assert admin.profile.color == "#0ea5e9"


def test_avatar_upload_resized_and_served(app, client, family_with_admin, login):
    admin, _ = family_with_admin
    login()
    resp = client.post("/profilo/foto", data={"avatar": (_png_bytes((2000, 1000)), "foto.png")},
                       content_type="multipart/form-data", follow_redirects=True)
    assert "Foto profilo aggiornata" in resp.get_data(as_text=True)
    filename = admin.profile.avatar_filename
    assert filename.endswith(".webp") and "foto" not in filename
    path = os.path.join(upload_dir("avatars"), filename)
    with Image.open(path) as img:
        assert max(img.size) <= app.config["AVATAR_SIZE"]
    resp = client.get(f"/profilo/avatar/{admin.profile.id}")
    assert resp.status_code == 200 and resp.mimetype == "image/webp"

    # sostituendo la foto, il file precedente viene eliminato
    client.post("/profilo/foto", data={"avatar": (_png_bytes(), "nuova.jpg")}, content_type="multipart/form-data")
    assert not os.path.exists(path)

    client.post("/profilo/foto/rimuovi")
    assert admin.profile.avatar_filename is None


def test_avatar_rejects_fake_image(client, family_with_admin, login):
    admin, _ = family_with_admin
    login()
    fake = io.BytesIO(b"<?php echo 'non sono una foto'; ?>")
    resp = client.post("/profilo/foto", data={"avatar": (fake, "foto.png")},
                       content_type="multipart/form-data", follow_redirects=True)
    assert "non è un&#39;immagine valida" in resp.get_data(as_text=True)
    assert admin.profile.avatar_filename is None
    resp = client.post("/profilo/foto", data={"avatar": (io.BytesIO(b"x"), "script.svg")},
                       content_type="multipart/form-data", follow_redirects=True)
    assert "Solo immagini" in resp.get_data(as_text=True)


def test_upload_too_large(app, client, family_with_admin, login):
    login()
    app.config["MAX_CONTENT_LENGTH"] = 1024
    resp = client.post("/profilo/foto", data={"avatar": (_png_bytes((1500, 1500)), "big.png")},
                       content_type="multipart/form-data")
    assert resp.status_code == 413


def test_theme_preferences(client, family_with_admin, login):
    admin, _ = family_with_admin
    login()
    client.post("/profilo/preferenze", data={"theme": "dark"})
    assert admin.theme == "dark"
    html = client.get("/").get_data(as_text=True)
    assert 'data-theme-pref="dark"' in html
    client.post("/profilo/tema", data={"next": "/"})
    assert admin.theme == "auto"
    client.post("/profilo/preferenze", data={"theme": "rosa"})
    assert admin.theme == "auto"


def test_csrf_protection(app, client, make_user):
    make_user()
    app.config["WTF_CSRF_ENABLED"] = True
    resp = client.post("/accedi", data={"email": "anna@famiglia.it", "password": "Password-123"})
    assert resp.status_code == 400
    assert "Sessione scaduta" in resp.get_data(as_text=True)


def test_security_headers_and_errors(client):
    resp = client.get("/accedi")
    assert "default-src 'self'" in resp.headers["Content-Security-Policy"]
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    resp = client.get("/pagina-inesistente")
    assert resp.status_code == 404 and "Pagina non trovata" in resp.get_data(as_text=True)


def test_pwa_endpoints(client):
    assert client.get("/manifest.webmanifest").status_code == 200
    resp = client.get("/sw.js")
    assert resp.status_code == 200 and resp.headers["Service-Worker-Allowed"] == "/"
    assert client.get("/offline").status_code == 200
    assert client.get("/health").get_json() == {"status": "ok"}


def test_timezone_roundtrip_with_dst(app):
    from datetime import datetime

    # 30 marzo 2025: in Italia l'ora legale inizia alle 02:00 → 03:00
    winter = to_utc(datetime(2025, 3, 29, 12, 0))
    summer = to_utc(datetime(2025, 3, 31, 12, 0))
    assert winter.hour == 11  # UTC+1
    assert summer.hour == 10  # UTC+2
    assert to_local(summer).hour == 12


def test_cli_reset_password(app, make_user):
    user = make_user()
    runner = app.test_cli_runner()
    result = runner.invoke(args=["lt", "reset-password", "anna@famiglia.it", "--password", "Ripristino-789"])
    assert result.exit_code == 0, result.output
    db.session.refresh(user)
    assert user.check_password("Ripristino-789")
