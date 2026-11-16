import io
import os
import zipfile
from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest
from openpyxl import load_workbook

from app.extensions import db
from app.models import Notification, Reminder
from app.services import backup_service, catalog_service, entry_service, family_service, reminder_service, \
    summary_service
from app.services.entry_service import EntryData
from app.utils.timezone import local_today, utcnow


@pytest.fixture()
def base(family_with_admin):
    admin, family = family_with_admin
    actor = family_service.membership_for(admin, family.id)
    cat = catalog_service.create_category(actor, name="Sport")
    bike = catalog_service.create_activity(actor, {"name": "Ciclismo", "category_id": cat.id,
                                                   "default_scope": "personal", "count_label": "uscite"})
    km = catalog_service.add_metric(actor, bike, {"name": "Km", "data_type": "decimal", "unit": "km",
                                                  "kind": "distance", "aggregation": "sum"})
    dur = catalog_service.add_metric(actor, bike, {"name": "Durata", "data_type": "duration", "kind": "duration",
                                                   "aggregation": "sum"})
    entry_service.create_entry(actor, EntryData(
        activity_id=bike.id, performed_by_profile_id=actor.profile_id, occurred_at=utcnow(), quantity=Decimal(1),
        scope="personal", visibility="family", description="Giro; con punto e virgola",
        metric_inputs={km.id: "42,5", dur.id: "1:30"}, new_tags=["lago"]))
    return {"admin": admin, "actor": actor, "bike": bike}


def test_reminder_schedule_rules():
    r = Reminder(frequency="weekly", time_of_day=time(7, 30), start_date=date(2026, 11, 1), weekdays="0,3")
    # lunedì 16/11/2026 alle 8:00 → prossimo giovedì 19/11 alle 7:30
    assert reminder_service.next_occurrence(r, datetime(2026, 11, 16, 8, 0)) == datetime(2026, 11, 19, 7, 30)
    r = Reminder(frequency="monthly", time_of_day=time(9, 0), start_date=date(2026, 1, 31), day_of_month=31)
    assert reminder_service.next_occurrence(r, datetime(2026, 2, 1)) == datetime(2026, 2, 28, 9, 0)
    r = Reminder(frequency="once", time_of_day=time(9, 0), start_date=date(2026, 1, 1))
    assert reminder_service.next_occurrence(r, datetime(2026, 2, 1)) is None


def test_reminders_page_and_scheduler(client, base, login, app):
    login()
    resp = client.post("/strumenti/promemoria", data={
        "title": "Bici!", "activity_id": base["bike"].id, "frequency": "daily", "time_of_day": "07:00",
        "start_date": local_today().isoformat()}, follow_redirects=True)
    assert "Promemoria creato" in resp.get_data(as_text=True)
    reminder = db.session.scalar(db.select(Reminder))
    first_run = reminder.next_run_at
    sent = reminder_service.run_due(now=first_run + timedelta(minutes=1))
    assert sent == 1 and reminder.next_run_at > first_run
    assert reminder_service.run_due(now=first_run + timedelta(minutes=2)) == 0  # niente doppioni
    note = db.session.scalar(db.select(Notification))
    assert note.title == "Bici!" and note.link == f"/registrazioni/nuova?attivita={base['bike'].id}"
    # campanella e apertura notifica
    html = client.get("/").get_data(as_text=True)
    assert "lt-bell-badge" in html
    resp = client.post(f"/notifiche/{note.id}/apri")
    assert resp.status_code == 302 and resp.headers["Location"].endswith(note.link)
    assert note.is_read
    assert client.get("/notifiche/conteggio").get_json() == {"unread": 0}


def test_weekly_reminder_requires_days(client, base, login):
    login()
    resp = client.post("/strumenti/promemoria", data={"title": "X", "activity_id": 0, "frequency": "weekly",
                                                      "time_of_day": "07:00", "start_date": local_today().isoformat()},
                       follow_redirects=True)
    assert "almeno un giorno" in resp.get_data(as_text=True)


def test_other_user_cannot_touch_reminder(client, base, make_user, login):
    r = reminder_service.save(base["actor"], None, {"title": "Mio", "frequency": "daily", "time_of_day": time(7),
                                                    "start_date": local_today()})
    luca = make_user("luca@famiglia.it", "Luca")
    _, code = family_service.create_invitation(base["actor"], "member", 3, None)
    family_service.accept_invitation(luca, code)
    login("luca@famiglia.it")
    assert client.post(f"/strumenti/promemoria/{r.id}/elimina").status_code == 404
    assert "Mio" not in client.get("/strumenti/promemoria").get_data(as_text=True)


def test_summaries(client, base, login):
    sent = summary_service.send_due_summaries()
    assert sent == 2  # settimanale + mensile
    assert summary_service.send_due_summaries() == 0
    login()
    html = client.get("/riepiloghi?tipo=settimana").get_data(as_text=True)
    assert "Riepilogo della settimana" in html and "Ciclismo" in html
    assert client.get("/riepiloghi?tipo=mese").status_code == 200


def test_preferences_disable_summaries(client, base, login):
    login()
    client.post("/profilo/preferenze", data={"theme": "auto", "goal_notifications": "y"})
    assert base["admin"].weekly_summary is False and base["admin"].goal_notifications is True
    assert summary_service.send_due_summaries() == 0


def test_export_csv_and_xlsx(client, base, login):
    login()
    resp = client.get("/strumenti/esporta?formato=csv&persona=0&categoria=0&attivita=0")
    text = resp.data.decode("utf-8-sig")
    assert resp.mimetype == "text/csv"
    header, row = text.splitlines()[:2]
    assert "Ciclismo · Km (km)" in header and "42,5" in row and "1:30" in row and '"Giro; con punto e virgola"' in row
    resp = client.get("/strumenti/esporta?formato=xlsx&persona=0&categoria=0&attivita=0")
    wb = load_workbook(io.BytesIO(resp.data))
    ws = wb["Registrazioni"]
    headers = [c.value for c in ws[1]]
    assert ws.cell(2, headers.index("Ciclismo · Km (km)") + 1).value == 42.5
    assert wb["Riepilogo"].cell(2, 1).value == "Ciclismo"
    # filtro per periodo senza risultati
    resp = client.get("/strumenti/esporta?formato=csv&persona=0&categoria=0&attivita=0&da=2000-01-01&a=2000-01-02")
    assert len(resp.data.decode("utf-8-sig").strip().splitlines()) == 1


def test_backup_and_cli(tmp_path, monkeypatch):
    from app import create_app
    from app.extensions import db as _db
    from app.services import auth_service

    db_file = tmp_path / "b.db"
    from app import config

    monkeypatch.setattr(config.TestingConfig, "SQLALCHEMY_DATABASE_URI", f"sqlite:///{db_file}")
    app = create_app("testing")
    app.config.update(BACKUP_FOLDER=str(tmp_path / "bk"), UPLOAD_FOLDER=str(tmp_path / "up"), BACKUP_KEEP=2)
    os.makedirs(tmp_path / "up" / "avatars")
    (tmp_path / "up" / "avatars" / "a.webp").write_bytes(b"img")
    with app.app_context():
        _db.create_all()
        auth_service.register_user("x@famiglia.it", "Password-123", "X")
        path = backup_service.create_backup()
        with zipfile.ZipFile(path) as z:
            assert set(z.namelist()) == {"lifetracker.db", "uploads/avatars/a.webp"}
        result = app.test_cli_runner().invoke(args=["lt", "run-scheduled"])
        assert result.exit_code == 0 and "backup=non necessario" in result.output
        for _ in range(3):
            backup_service.create_backup()
        assert len(backup_service.list_backups()) == 2
        _db.session.remove()
