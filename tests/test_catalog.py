import pytest

from app.extensions import db
from app.models import ROLE_MEMBER, Activity, Category, MetricDefinition, Tag
from app.services import PermissionDenied, ServiceError, catalog_service, family_service


def _actor(user, family):
    return family_service.membership_for(user, family.id)


@pytest.fixture()
def sport(family_with_admin):
    admin, family = family_with_admin
    actor = _actor(admin, family)
    cat = catalog_service.create_category(actor, name="Sport", icon="trophy", color="#ef4444")
    bike = catalog_service.create_activity(actor, {
        "name": "Ciclismo", "category_id": cat.id, "icon": "bicycle", "count_label": "uscite",
        "default_quantity": 1, "default_scope": "personal", "is_quick": True,
    })
    return actor, cat, bike


def test_category_and_subcategory_pages(client, family_with_admin, login):
    login()
    resp = client.post("/catalogo/categorie/nuova", data={"name": "Sport", "parent_id": 0, "icon": "trophy",
                                                         "color": "#ef4444", "sort_order": 1}, follow_redirects=True)
    assert "Categoria creata" in resp.get_data(as_text=True)
    sport = db.session.scalar(db.select(Category).filter_by(name="Sport"))
    resp = client.post("/catalogo/categorie/nuova", data={"name": "Acqua", "parent_id": sport.id, "icon": "water",
                                                         "color": "#0ea5e9"}, follow_redirects=True)
    html = resp.get_data(as_text=True)
    assert "Acqua" in html and "Sport" in html
    sub = db.session.scalar(db.select(Category).filter_by(name="Acqua"))
    assert sub.parent_id == sport.id and sub.full_name == "Sport › Acqua"
    # icona non presente nella lista → rifiutata dal form
    resp = client.post("/catalogo/categorie/nuova", data={"name": "X", "parent_id": 0, "icon": "javascript:x",
                                                         "color": "#000000"})
    assert db.session.scalar(db.select(Category).filter_by(name="X")) is None


def test_subcategory_depth_limited(sport):
    actor, cat, _ = sport
    sub = catalog_service.create_category(actor, name="Strada", parent_id=cat.id)
    with pytest.raises(ServiceError):
        catalog_service.create_category(actor, name="Gare", parent_id=sub.id)


def test_activity_with_metrics(client, sport, login):
    actor, cat, bike = sport
    login()
    resp = client.post(f"/catalogo/attivita/{bike.id}/indicatori", data={
        "name": "Chilometri", "data_type": "decimal", "unit": "km", "kind": "distance", "aggregation": "sum",
        "min_value": "0", "sort_order": 1}, follow_redirects=True)
    assert "Indicatore aggiunto" in resp.get_data(as_text=True)
    client.post(f"/catalogo/attivita/{bike.id}/indicatori", data={
        "name": "Durata", "data_type": "duration", "kind": "other", "aggregation": "sum"})
    client.post(f"/catalogo/attivita/{bike.id}/indicatori", data={
        "name": "Frequenza cardiaca", "data_type": "integer", "unit": "bpm", "kind": "heart_rate", "aggregation": "avg"})
    metrics = {m.key: m for m in bike.metrics}
    assert set(metrics) == {"chilometri", "durata", "frequenza_cardiaca"}
    assert metrics["durata"].kind == "duration"  # la durata ha sempre significato "durata"
    html = client.get(f"/catalogo/attivita/{bike.id}").get_data(as_text=True)
    assert "Chilometri" in html and "Media" in html


def test_metric_validation(sport):
    actor, _, bike = sport
    base = {"name": "Km", "data_type": "decimal", "unit": "km", "kind": "distance", "aggregation": "sum"}
    catalog_service.add_metric(actor, bike, base)
    with pytest.raises(ServiceError, match="già un indicatore"):
        catalog_service.add_metric(actor, bike, base)
    with pytest.raises(ServiceError, match="minimo"):
        catalog_service.add_metric(actor, bike, {**base, "name": "X", "min_value": 5, "max_value": 1})


def test_duplicate_activity_name(sport):
    actor, cat, _ = sport
    with pytest.raises(ServiceError, match="Esiste già"):
        catalog_service.create_activity(actor, {"name": "Ciclismo", "category_id": cat.id, "default_scope": "personal"})


def test_delete_category_with_activities_blocked_archive_ok(client, sport, login):
    actor, cat, bike = sport
    login()
    resp = client.post(f"/catalogo/categorie/{cat.id}/elimina", follow_redirects=True)
    assert "archiviala" in resp.get_data(as_text=True)
    client.post(f"/catalogo/categorie/{cat.id}/archivia")
    assert cat.is_archived
    assert bike not in catalog_service.active_activities(actor.family_id)
    client.post(f"/catalogo/categorie/{cat.id}/archivia")
    assert not cat.is_archived


def test_member_permissions(sport, make_user):
    actor, cat, bike = sport
    luca = make_user("luca@famiglia.it", "Luca")
    _, code = family_service.create_invitation(actor, ROLE_MEMBER, 3, None)
    luca_m = family_service.accept_invitation(luca, code)
    # un membro può creare...
    mine = catalog_service.create_activity(luca_m, {"name": "Corsa", "category_id": cat.id, "default_scope": "personal"})
    catalog_service.update_activity(luca_m, mine, {"name": "Corsa su strada", "category_id": cat.id,
                                                   "default_scope": "personal"})
    # ...ma non modificare ciò che hanno creato altri
    with pytest.raises(PermissionDenied):
        catalog_service.update_activity(luca_m, bike, {"name": "X", "category_id": cat.id, "default_scope": "personal"})
    with pytest.raises(PermissionDenied):
        catalog_service.delete_category(luca_m, cat)


def test_catalog_isolation(client, sport, make_user, login):
    actor, cat, bike = sport
    other = make_user("mario@famiglia.it", "Mario")
    family_service.create_family(other, "Verdi")
    login("mario@famiglia.it")
    assert client.get(f"/catalogo/attivita/{bike.id}").status_code == 404
    assert client.get(f"/catalogo/categorie/{cat.id}/modifica").status_code == 404
    assert client.post(f"/catalogo/attivita/{bike.id}/indicatori", data={
        "name": "X", "data_type": "decimal", "kind": "other", "aggregation": "sum"}).status_code == 404
    # una categoria di un'altra famiglia non può essere usata come genitore
    client.post("/catalogo/categorie/nuova", data={"name": "Furba", "parent_id": cat.id, "icon": "tag",
                                                         "color": "#000000"})
    assert db.session.scalar(db.select(Category).filter_by(name="Furba")) is None
    assert "Ciclismo" not in client.get("/catalogo/").get_data(as_text=True)


def test_tags(client, family_with_admin, login):
    login()
    client.post("/catalogo/tag", data={"name": "#vacanza", "color": "#10b981"})
    tag = db.session.scalar(db.select(Tag))
    assert tag.name == "vacanza"
    resp = client.post("/catalogo/tag", data={"name": "vacanza", "color": "#10b981"}, follow_redirects=True)
    assert "Esiste già" in resp.get_data(as_text=True)
    client.post(f"/catalogo/tag/{tag.id}/elimina")
    assert db.session.scalar(db.select(Tag)) is None


def test_delete_unused_activity_and_metric(sport):
    actor, _, bike = sport
    m = catalog_service.add_metric(actor, bike, {"name": "Km", "data_type": "decimal", "kind": "distance",
                                                  "aggregation": "sum"})
    catalog_service.delete_metric(actor, m)
    assert db.session.get(MetricDefinition, m.id) is None
    catalog_service.delete_activity(actor, bike)
    assert db.session.get(Activity, bike.id) is None
