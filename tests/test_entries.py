import io
from decimal import Decimal

import pytest
from PIL import Image

from app.extensions import db
from app.models import ROLE_MEMBER, ActivityEntry, Attachment, EntryRevision, Tag
from app.services import PermissionDenied, catalog_service, entry_service, family_service
from app.services.entry_service import EntryData
from app.utils.timezone import utcnow


def _actor(user, family):
    return family_service.membership_for(user, family.id)


@pytest.fixture()
def setup(family_with_admin):
    """Famiglia con attività Ciclismo (km, durata, fc media, note testo) e dipendente Sofia."""
    admin, family = family_with_admin
    actor = _actor(admin, family)
    cat = catalog_service.create_category(actor, name="Sport")
    bike = catalog_service.create_activity(actor, {"name": "Ciclismo", "category_id": cat.id, "count_label": "uscite",
                                                   "default_quantity": 1, "default_scope": "personal", "is_quick": True})
    km = catalog_service.add_metric(actor, bike, {"name": "Km", "data_type": "decimal", "unit": "km",
                                                  "kind": "distance", "aggregation": "sum", "min_value": 0,
                                                  "is_required": True})
    dur = catalog_service.add_metric(actor, bike, {"name": "Durata", "data_type": "duration", "kind": "duration",
                                                   "aggregation": "sum"})
    hr = catalog_service.add_metric(actor, bike, {"name": "FC", "data_type": "integer", "unit": "bpm",
                                                  "kind": "heart_rate", "aggregation": "avg", "max_value": 230})
    sofia = family_service.add_dependent(actor, "Sofia", None, "#10b981")
    return {"admin": admin, "family": family, "actor": actor, "bike": bike, "km": km, "dur": dur, "hr": hr,
            "sofia": sofia}


def _form(s, **over):
    data = {"activity_id": s["bike"].id, "performed_by_profile_id": s["admin"].profile.id,
            "occurred_date": "2026-11-10", "occurred_time": "18:30", "quantity": "1", "scope": "personal",
            "visibility": "family", f"m_{s['km'].id}": "42,5", f"m_{s['dur'].id}": "1:45", f"m_{s['hr'].id}": "142",
            "description": "Giro del lago", "new_tags": "lago, allenamento"}
    data.update(over)
    return data


def test_quick_add_json_and_fallback(client, setup, login):
    login()
    resp = client.post(f"/registrazioni/rapida/{setup['bike'].id}", headers={"Accept": "application/json"})
    data = resp.get_json()
    assert resp.status_code == 200 and data["ok"] and data["message"] == "Ciclismo +1"
    entry = db.session.get(ActivityEntry, data["entry_id"])
    assert entry.quantity == 1 and entry.performed_by_profile_id == setup["admin"].profile.id
    assert entry.created_by_user_id == setup["admin"].id
    assert len(entry.revisions) == 1 and entry.revisions[0].action == "create"
    # per un profilo dipendente, senza JavaScript
    resp = client.post(f"/registrazioni/rapida/{setup['bike'].id}",
                       data={"performed_by_profile_id": setup["sofia"].id}, follow_redirects=True)
    assert "per Sofia" in resp.get_data(as_text=True)
    assert "Ciclismo" in client.get("/registrazioni/rapida").get_data(as_text=True)


def test_full_entry_with_metrics_tags_and_timezone(client, setup, login):
    login()
    resp = client.post(f"/registrazioni/nuova?attivita={setup['bike'].id}", data=_form(setup), follow_redirects=True)
    html = resp.get_data(as_text=True)
    assert "Ciclismo registrata" in html and "42,5 km" in html and "1:45" in html
    entry = db.session.scalar(db.select(ActivityEntry))
    assert entry.occurred_at.hour == 17  # 18:30 a Roma (UTC+1 a novembre) = 17:30 UTC
    values = {v.definition.key: v.value_numeric for v in entry.metric_values}
    assert values == {"km": Decimal("42.5"), "durata": Decimal(6300), "fc": Decimal(142)}
    assert sorted(t.name for t in entry.tags) == ["allenamento", "lago"]


def test_metric_validation_errors(client, setup, login):
    login()
    resp = client.post(f"/registrazioni/nuova?attivita={setup['bike'].id}",
                       data=_form(setup, **{f"m_{setup['km'].id}": "", f"m_{setup['hr'].id}": "300",
                                            f"m_{setup['dur'].id}": "abc"}))
    html = resp.get_data(as_text=True)
    assert "Campo obbligatorio" in html and "Il valore massimo è 230" in html and "Durata non valida" in html
    assert db.session.scalar(db.select(db.func.count()).select_from(ActivityEntry)) == 0
    resp = client.post(f"/registrazioni/nuova?attivita={setup['bike'].id}",
                       data=_form(setup, **{f"m_{setup['hr'].id}": "140,5"}))
    assert "numero intero" in resp.get_data(as_text=True)


def test_edit_creates_revision_with_diff(client, setup, login):
    login()
    client.post(f"/registrazioni/nuova?attivita={setup['bike'].id}", data=_form(setup))
    entry = db.session.scalar(db.select(ActivityEntry))
    client.post(f"/registrazioni/{entry.id}/modifica", data=_form(setup, **{f"m_{setup['km'].id}": "50"}))
    html = client.get(f"/registrazioni/{entry.id}").get_data(as_text=True)
    assert "Modificata" in html and "42,5 km" in html and "50 km" in html
    assert db.session.scalar(db.select(db.func.count()).select_from(EntryRevision)) == 2


def test_soft_delete_restore_purge(client, setup, login):
    login()
    entry = entry_service.quick_add(setup["actor"], setup["bike"].id)
    client.post(f"/registrazioni/{entry.id}/elimina")
    assert entry.deleted_at is not None
    assert "0 registrazioni trovate" in client.get("/registrazioni/").get_data(as_text=True)
    assert "1 registrazioni trovate" in client.get("/registrazioni/?stato=eliminate").get_data(as_text=True)
    client.post(f"/registrazioni/{entry.id}/ripristina")
    assert entry.deleted_at is None
    client.post(f"/registrazioni/{entry.id}/elimina")
    client.post(f"/registrazioni/{entry.id}/elimina-definitivamente")
    assert db.session.get(ActivityEntry, entry.id) is None


def test_privacy_and_permissions(client, setup, make_user, login):
    s = setup
    luca = make_user("luca@famiglia.it", "Luca")
    _, code = family_service.create_invitation(s["actor"], ROLE_MEMBER, 3, None)
    luca_m = family_service.accept_invitation(luca, code)
    # un membro non può registrare per un altro adulto, ma sì per i dipendenti
    with pytest.raises(PermissionDenied):
        entry_service.quick_add(luca_m, s["bike"].id, s["admin"].profile.id)
    entry_service.quick_add(luca_m, s["bike"].id, s["sofia"].id)
    # registrazione privata dell'admin: Luca non la vede
    private = entry_service.create_entry(s["actor"], EntryData(
        activity_id=s["bike"].id, performed_by_profile_id=s["admin"].profile.id, occurred_at=utcnow(),
        quantity=Decimal(1), scope="personal", visibility="private", metric_inputs={s["km"].id: "10"}))
    public = entry_service.quick_add(s["actor"], s["bike"].id)
    login("luca@famiglia.it")
    assert client.get(f"/registrazioni/{private.id}").status_code == 404
    assert client.get(f"/registrazioni/{public.id}").status_code == 200
    # Luca vede ma non può modificare la registrazione dell'admin
    assert client.get(f"/registrazioni/{public.id}/modifica").status_code == 403
    assert client.post(f"/registrazioni/{public.id}/elimina").status_code == 403


def test_isolation_between_families(client, setup, make_user, login):
    entry = entry_service.quick_add(setup["actor"], setup["bike"].id)
    other = make_user("mario@famiglia.it", "Mario")
    family_service.create_family(other, "Verdi")
    login("mario@famiglia.it")
    assert client.get(f"/registrazioni/{entry.id}").status_code == 404
    assert client.post(f"/registrazioni/rapida/{setup['bike'].id}").status_code in (302, 400)
    assert db.session.scalar(db.select(db.func.count()).select_from(ActivityEntry)) == 1
    client.post(f"/registrazioni/nuova?attivita={setup['bike'].id}", data=_form(setup))
    assert db.session.scalar(db.select(db.func.count()).select_from(ActivityEntry)) == 1


def test_attachments(client, setup, login):
    login()
    buf = io.BytesIO()
    Image.new("RGB", (3000, 2000), (10, 120, 200)).save(buf, "JPEG")
    buf.seek(0)
    data = _form(setup)
    data["attachments"] = [(buf, "giro.jpg"), (io.BytesIO(b"%PDF-1.4 test"), "percorso.pdf")]
    client.post(f"/registrazioni/nuova?attivita={setup['bike'].id}", data=data, content_type="multipart/form-data")
    entry = db.session.scalar(db.select(ActivityEntry))
    assert len(entry.attachments) == 2
    image = next(a for a in entry.attachments if a.is_image)
    resp = client.get(f"/registrazioni/allegati/{image.id}")
    assert resp.status_code == 200 and resp.mimetype == "image/webp"
    # PDF falso rifiutato
    data = _form(setup)
    data["attachments"] = [(io.BytesIO(b"<html>"), "finto.pdf")]
    resp = client.post(f"/registrazioni/{entry.id}/modifica", data=data, content_type="multipart/form-data")
    assert "non è un PDF valido" in resp.get_data(as_text=True)
    client.post(f"/registrazioni/allegati/{image.id}/elimina")
    assert db.session.get(Attachment, image.id) is None


def test_filters(client, setup, login):
    login()
    entry_service.quick_add(setup["actor"], setup["bike"].id, setup["sofia"].id)
    client.post(f"/registrazioni/nuova?attivita={setup['bike'].id}", data=_form(setup))
    html = client.get(f"/registrazioni/?persona={setup['sofia'].id}").get_data(as_text=True)
    assert "1 registrazioni trovate" in html
    tag = db.session.scalar(db.select(Tag).filter_by(name="lago"))
    html = client.get(f"/registrazioni/?tag={tag.id}&da=2026-11-10&a=2026-11-10").get_data(as_text=True)
    assert "1 registrazioni trovate" in html and "Giro del lago" in html
    html = client.get("/registrazioni/?q=lago").get_data(as_text=True)
    assert "1 registrazioni trovate" in html


def test_activity_with_entries_cannot_be_deleted(setup):
    entry_service.quick_add(setup["actor"], setup["bike"].id)
    from app.services import ServiceError

    with pytest.raises(ServiceError, match="archiviala"):
        catalog_service.delete_activity(setup["actor"], setup["bike"])


def test_removing_dependent_keeps_history(setup):
    entry_service.quick_add(setup["actor"], setup["bike"].id, setup["sofia"].id)
    member = family_service.get_dependent_or_none(setup["family"], setup["sofia"].id)
    family_service.remove_member(setup["actor"], member)
    entry = db.session.scalar(db.select(ActivityEntry))
    assert entry.performed_by.display_name == "Sofia"


def test_delete_family_with_entries(client, setup, login):
    entry_service.quick_add(setup["actor"], setup["bike"].id, setup["sofia"].id)
    login()
    client.post("/famiglia/elimina", data={"del-confirm_name": "Famiglia Rossi"})
    assert db.session.scalar(db.select(db.func.count()).select_from(ActivityEntry)) == 0
