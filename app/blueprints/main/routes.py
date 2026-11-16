from flask import current_app, redirect, render_template, send_from_directory, url_for
from flask_login import current_user

from app.blueprints.main import bp
from app.extensions import db
from app.services import family_service
from app.utils.security import get_current_membership
from app.utils.timezone import to_local


@bp.route("/")
def home():
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))
    membership = get_current_membership()
    if membership is None:
        return redirect(url_for("family.welcome"))
    from app.services import catalog_service, entry_service, goal_service, stats_service
    from app.services.period import period_for
    from app.services.stats_service import StatsFilters

    week = period_for("week")
    today = period_for("day")
    filters = StatsFilters(period=week)
    week_entries = stats_service.load_entries(membership, week, filters, profile_id=membership.profile_id)
    today_entries = stats_service.load_entries(membership, today, filters, profile_id=membership.profile_id)
    family_today = stats_service.load_entries(membership, today, StatsFilters(period=today))
    return render_template(
        "main/home.html",
        membership=membership,
        members=family_service.family_members(membership.family),
        quick=catalog_service.quick_activities(membership.family_id)[:8],
        has_catalog=bool(catalog_service.active_activities(membership.family_id)),
        recent=entry_service.recent_entries(membership, 6),
        goals=goal_service.dashboard_goals(membership, personal=True)[:4],
        today_count=len(today_entries),
        family_today_count=len(family_today),
        week_count=len(week_entries),
        week_time=stats_service.fmt_hours(stats_service.duration_seconds(week_entries)),
        week_days=len({to_local(e.occurred_at).date() for e in week_entries}),
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
