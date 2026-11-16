from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import Goal, Notification
from app.services import ServiceError, catalog_service, entry_service, family_service, goal_service, stats_service
from app.services.entry_service import EntryData
from app.services.period import Period, period_for
from app.services.stats_service import StatsFilters
from app.utils.timezone import local_today, to_utc


@pytest.fixture()
def data(family_with_admin):
    admin, family = family_with_admin
    actor = family_service.membership_for(admin, family.id)
    sport = catalog_service.create_category(actor, name="Sport", color="#ef4444")
    study = catalog_service.create_category(actor, name="Formazione", color="#0ea5e9")
    bike = catalog_service.create_activity(actor, {"name": "Ciclismo", "category_id": sport.id,
                                                   "default_scope": "personal", "count_label": "uscite"})
    run = catalog_service.create_activity(actor, {"name": "Corsa", "category_id": sport.id, "default_scope": "personal"})
    read = catalog_service.create_activity(actor, {"name": "Lettura", "category_id": study.id,
                                                   "default_scope": "personal", "count_label": "sessioni"})
    km_bike = catalog_service.add_metric(actor, bike, {"name": "Km", "data_type": "decimal", "unit": "km",
                                                       "kind": "distance", "aggregation": "sum"})
    km_run = catalog_service.add_metric(actor, run, {"name": "Distanza", "data_type": "decimal", "unit": "km",
                                                     "kind": "distance", "aggregation": "sum"})
    hr = catalog_service.add_metric(actor, bike, {"name": "FC", "data_type": "integer", "unit": "bpm",
                                                  "kind": "heart_rate", "aggregation": "avg"})
    minutes = catalog_service.add_metric(actor, read, {"name": "Durata", "data_type": "duration",
                                                       "kind": "duration", "aggregation": "sum"})
    sofia = family_service.add_dependent(actor, "Sofia", None, "#10b981")
    today = local_today()

    def add(activity, when: date, metrics=None, who=None, scope="personal", qty=1):
        return entry_service.create_entry(actor, EntryData(
            activity_id=activity.id, performed_by_profile_id=who or actor.profile_id,
            occurred_at=to_utc(datetime.combine(when, datetime.min.time()).replace(hour=10)),
            quantity=Decimal(qty), scope=scope, visibility="family", metric_inputs=metrics or {}))

    add(bike, today, {km_bike.id: "40", hr.id: "140"})
    add(bike, today, {km_bike.id: "20", hr.id: "150"})
    add(run, today, {km_run.id: "10"})
    add(read, today, {minutes.id: "1:30"}, who=sofia.id, scope="family")
    return locals()


def test_measures_are_homogeneous(data):
    measures = stats_service.available_measures(data["family"].id)
    keys = {m.key for m in measures}
    assert "g:distance|km|sum" in keys and "g:heart_rate|bpm|avg" in keys and "g:duration|h|sum" in keys
    assert "quantity" not in keys  # la quantità ha senso solo per una singola attività
    period = period_for("month")
    entries = stats_service.load_entries(data["actor"], period, StatsFilters(period=period))
    distance = stats_service.resolve_measure(measures, "g:distance|km|sum")
    assert stats_service.aggregate(entries, distance) == 70  # bici + corsa, stessa unità
    hr = stats_service.resolve_measure(measures, "g:heart_rate|bpm|avg")
    assert stats_service.aggregate(entries, hr) == 145  # media, non somma
    assert stats_service.duration_seconds(entries) == 5400
    by_activity = stats_service.available_measures(data["family"].id, data["bike"].id)
    assert {m.key for m in by_activity} >= {"count", "quantity", f"m:{data['km_bike'].id}"}


def test_dashboards_render(client, data, login):
    login()
    html = client.get("/dashboard/").get_data(as_text=True)
    assert "Dashboard personale" in html and "Ciclismo" in html and 'data-chart="cTrend"' in html
    html = client.get("/dashboard/famiglia").get_data(as_text=True)
    assert "Sofia" in html and "Attività condivise" in html
    for view in ("persone", "periodi", "categorie", "attivita", "io-famiglia"):
        resp = client.get(f"/dashboard/confronti?vista={view}&misura=g:distance|km|sum")
        assert resp.status_code == 200, view
    for p in ("day", "week", "quarter", "semester", "year"):
        assert client.get(f"/dashboard/?periodo={p}").status_code == 200
    resp = client.get("/dashboard/?periodo=custom&da=2026-01-01&a=2026-03-31")
    assert "01/01/2026 – 31/03/2026" in resp.get_data(as_text=True)
    resp = client.get(f"/dashboard/?attivita={data['bike'].id}&misura=quantity")
    assert "Quantità (uscite)" in resp.get_data(as_text=True)


def test_personal_dashboard_only_my_entries(data):
    period = period_for("month")
    filters = StatsFilters(period=period)
    mine = stats_service.load_entries(data["actor"], period, filters, profile_id=data["actor"].profile_id)
    assert len(mine) == 3
    everyone = stats_service.load_entries(data["actor"], period, filters)
    assert len(everyone) == 4


def test_period_boundaries_and_previous():
    p = period_for("quarter", date(2026, 5, 17))
    assert (p.start, p.end) == (date(2026, 4, 1), date(2026, 6, 30))
    assert p.previous().start == date(2026, 1, 1)
    w = period_for("week", date(2026, 11, 18))
    assert w.start == date(2026, 11, 16) and w.end == date(2026, 11, 22)
    s = period_for("semester", date(2026, 11, 18))
    assert s.start == date(2026, 7, 1) and s.label == "2° semestre 2026"
    custom = Period("custom", date(2026, 1, 1), date(2026, 1, 10))
    assert custom.previous().end == date(2025, 12, 31) and custom.previous().days == 10


def test_goal_progress_and_notifications(data):
    actor = data["actor"]
    today = local_today()
    goal = goal_service.create_goal(actor, {
        "title": "100 km di sport", "scope": "personal", "owner_profile_id": actor.profile_id,
        "target_type": "metric", "metric_definition_id": data["km_bike"].id, "target_value": 100,
        "recurrence": "none", "start_date": today - timedelta(days=1), "end_date": today + timedelta(days=30),
    })
    p = goal_service.compute(goal)
    assert p.value == 60 and p.pct == 60 and goal.status == "active"
    assert any(e.event == "progress_50" for e in goal.events)
    data["add"](data["bike"], today, {data["km_bike"].id: "45"})
    db.session.refresh(goal)
    assert goal.status == "completed"
    titles = [n.title for n in db.session.scalars(db.select(Notification))]
    assert any("Obiettivo raggiunto" in t for t in titles)
    assert sum("A metà strada" in t for t in titles) == 1  # nessun doppione


def test_recurring_family_goal_and_duration_target(data):
    actor = data["actor"]
    goal = goal_service.create_goal(actor, {
        "title": "Leggere 2 ore a settimana", "scope": "family", "target_type": "metric",
        "metric_definition_id": data["minutes"].id, "target_value": 120, "recurrence": "weekly",
        "start_date": local_today() - timedelta(days=60),
    })
    p = goal_service.compute(goal)
    assert p.value == 5400 and p.target == 7200 and p.pct == 75 and p.value_label == "1:30"
    assert len(goal_service.history_periods(goal)) == 8


def test_goal_validation_and_permissions(data, make_user):
    actor = data["actor"]
    with pytest.raises(ServiceError, match="scadenza"):
        goal_service.create_goal(actor, {"title": "X", "scope": "personal", "owner_profile_id": actor.profile_id,
                                         "target_type": "count", "target_value": 3, "recurrence": "none",
                                         "start_date": local_today()})
    luca = make_user("luca@famiglia.it", "Luca")
    _, code = family_service.create_invitation(actor, "member", 3, None)
    luca_m = family_service.accept_invitation(luca, code)
    from app.services import PermissionDenied

    with pytest.raises(PermissionDenied):
        goal_service.create_goal(luca_m, {"title": "Fam", "scope": "family", "target_type": "count",
                                          "target_value": 3, "recurrence": "weekly", "start_date": local_today()})
    private = goal_service.create_goal(actor, {"title": "Segreto", "scope": "personal", "visibility": "private",
                                               "owner_profile_id": actor.profile_id, "target_type": "count",
                                               "target_value": 3, "recurrence": "weekly",
                                               "start_date": local_today()})
    assert goal_service.get_visible_goal(luca_m, private.id) is None


def test_goal_expires(data):
    actor = data["actor"]
    goal = goal_service.create_goal(actor, {
        "title": "Tante corse", "scope": "personal", "owner_profile_id": actor.profile_id, "target_type": "count",
        "activity_id": data["run"].id, "target_value": 50, "recurrence": "none",
        "start_date": local_today() - timedelta(days=10), "end_date": local_today() + timedelta(days=1)})
    goal_service.evaluate(goal, today=local_today() + timedelta(days=5))
    assert goal.status == "expired"


def test_goal_pages(client, data, login):
    login()
    resp = client.post("/obiettivi/nuovo", data={
        "title": "3 uscite a settimana", "scope": "personal", "owner_profile_id": data["actor"].profile_id,
        "visibility": "family", "target_type": "quantity", "activity_id": data["bike"].id, "category_id": 0,
        "metric_definition_id": 0, "target_value": "3", "recurrence": "weekly",
        "start_date": local_today().isoformat()}, follow_redirects=True)
    html = resp.get_data(as_text=True)
    assert "Obiettivo creato" in html and "2 uscite" in html
    goal = db.session.scalar(db.select(Goal))
    assert "3 uscite a settimana" in client.get("/obiettivi/").get_data(as_text=True)
    assert "3 uscite a settimana" in client.get("/dashboard/").get_data(as_text=True)
    client.post(f"/obiettivi/{goal.id}/archivia")
    assert goal.status == "archived"
    assert "3 uscite a settimana" in client.get("/obiettivi/?stato=storico").get_data(as_text=True)


def test_calendar_views(client, data, login):
    login()
    for view in ("mese", "settimana", "giorno"):
        resp = client.get(f"/calendario/?vista={view}")
        assert resp.status_code == 200
        assert "Ciclismo" in resp.get_data(as_text=True)
    html = client.get(f"/calendario/?vista=giorno&persona={data['sofia'].id}").get_data(as_text=True)
    assert "Lettura" in html and "Ciclismo</span>" not in html
    html = client.get("/calendario/?vista=giorno").get_data(as_text=True)
    assert "1:30" in html or "1 h 30 min" in html


def test_home_dashboard(client, data, login):
    login()
    html = client.get("/").get_data(as_text=True)
    assert "Registra con un tocco" in html and "Ultime attività" in html and "Ciclismo" in html
