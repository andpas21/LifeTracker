from flask import current_app, redirect, render_template, send_from_directory, url_for
from flask_login import current_user

from app.blueprints.main import bp
from app.extensions import db
from app.services import family_service
from app.utils.security import get_current_membership


@bp.route("/")
def home():
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))
    membership = get_current_membership()
    if membership is None:
        return redirect(url_for("family.welcome"))
    return render_template(
        "main/home.html",
        membership=membership,
        members=family_service.family_members(membership.family),
    )


@bp.route("/offline")
def offline():
    return render_template("main/offline.html")


@bp.route("/sw.js")
def service_worker():
    # Servito dalla radice perché il service worker possa controllare tutto il sito.
    response = send_from_directory(current_app.static_folder, "js/sw.js", mimetype="application/javascript")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Service-Worker-Allowed"] = "/"
    return response


@bp.route("/manifest.webmanifest")
def manifest():
    return send_from_directory(
        current_app.static_folder, "manifest.webmanifest", mimetype="application/manifest+json"
    )


@bp.route("/health")
def health():
    """Controllo di stato per monitoraggio (usato anche dagli script di installazione)."""
    db.session.execute(db.text("SELECT 1"))
    return {"status": "ok"}
