from datetime import timedelta

import pytest

from app.extensions import db
from app.models import ROLE_ADMIN, ROLE_DEPENDENT, ROLE_MEMBER, Family, FamilyInvitation, FamilyMember, Profile
from app.services import ServiceError, family_service
from app.utils.timezone import utcnow
from tests.conftest import PASSWORD, extract_invite_code


def _member(user, family):
    return family_service.membership_for(user, family.id)


def test_create_family_makes_admin(client, make_user, login):
    make_user()
    login()
    resp = client.post("/famiglia/nuova", data={"name": "Famiglia Bianchi"}, follow_redirects=True)
    html = resp.get_data(as_text=True)
    assert "Famiglia Bianchi" in html and "Amministratore" in html
    family = db.session.scalar(db.select(Family))
    assert family.memberships[0].role == ROLE_ADMIN


def test_home_shows_family(client, family_with_admin, login):
    login()
    html = client.get("/").get_data(as_text=True)
    assert "Famiglia Rossi" in html and "Anna Rossi" in html


def test_invitation_flow_existing_user(client, family_with_admin, make_user, login):
    admin, family = family_with_admin
    make_user("luca@famiglia.it", "Luca Rossi")
    login()
    resp = client.post("/famiglia/inviti", data={"role": "member", "valid_days": 7, "note": "per Luca"},
                       follow_redirects=True)
    code = extract_invite_code(resp.get_data(as_text=True))
    # il codice in chiaro NON è salvato nel database
    assert db.session.scalar(db.select(FamilyInvitation)).code_hash != code
    client.post("/esci")

    login("luca@famiglia.it")
    resp = client.get(f"/famiglia/unisciti/{code}")
    assert "Famiglia Rossi" in resp.get_data(as_text=True)
    resp = client.post("/famiglia/unisciti", data={"code": code.lower()}, follow_redirects=True)
    assert "Ora fai parte della famiglia" in resp.get_data(as_text=True)
    invitation = db.session.scalar(db.select(FamilyInvitation))
    assert invitation.status == "accepted"
    assert len(family_service.family_members(family)) == 2

    # codice monouso
    resp = client.post("/famiglia/unisciti", data={"code": code}, follow_redirects=True)
    assert "non valido" in resp.get_data(as_text=True)


def test_register_with_invite_code_joins_family(client, family_with_admin):
    admin, family = family_with_admin
    _, code = family_service.create_invitation(_member(admin, family), ROLE_MEMBER, 3, None)
    resp = client.post(
        "/registrati",
        data={"display_name": "Giulia", "email": "giulia@famiglia.it", "password": PASSWORD,
              "confirm": PASSWORD, "invite_code": code},
        follow_redirects=True,
    )
    assert "Benvenuto nella famiglia Famiglia Rossi" in resp.get_data(as_text=True)


def test_expired_and_revoked_invitations_rejected(family_with_admin, make_user):
    admin, family = family_with_admin
    actor = _member(admin, family)
    inv, code = family_service.create_invitation(actor, ROLE_MEMBER, 1, None)
    inv.expires_at = utcnow() - timedelta(seconds=1)
    db.session.commit()
    other = make_user("x@famiglia.it", "X")
    with pytest.raises(ServiceError):
        family_service.accept_invitation(other, code)

    inv2, code2 = family_service.create_invitation(actor, ROLE_MEMBER, 1, None)
    family_service.revoke_invitation(actor, inv2.id)
    with pytest.raises(ServiceError):
        family_service.accept_invitation(other, code2)


def test_member_cannot_access_admin_pages(client, family_with_admin, make_user, login):
    admin, family = family_with_admin
    luca = make_user("luca@famiglia.it", "Luca")
    _, code = family_service.create_invitation(_member(admin, family), ROLE_MEMBER, 3, None)
    family_service.accept_invitation(luca, code)
    login("luca@famiglia.it")
    assert client.get("/famiglia/").status_code == 200
    for url in ("/famiglia/inviti", "/famiglia/impostazioni", "/famiglia/dipendenti/nuovo", "/famiglia/registro"):
        assert client.get(url).status_code == 403
    admin_member = _member(admin, family)
    resp = client.post(f"/famiglia/membri/{admin_member.id}/ruolo", data={"role": "member"})
    assert resp.status_code == 403
    db.session.refresh(admin_member)
    assert admin_member.role == ROLE_ADMIN


def test_family_data_isolation(client, family_with_admin, make_user, login):
    """Un amministratore di un'altra famiglia non può toccare membri/dipendenti/foto della prima."""
    admin, family = family_with_admin
    dep = family_service.add_dependent(_member(admin, family), "Sofia", None, "#10b981")
    other = make_user("mario@famiglia.it", "Mario Verdi")
    family_service.create_family(other, "Famiglia Verdi")
    login("mario@famiglia.it")

    anna_member = _member(admin, family)
    assert client.post(f"/famiglia/membri/{anna_member.id}/rimuovi").status_code == 404
    assert client.post(f"/famiglia/membri/{anna_member.id}/ruolo", data={"role": "member"}).status_code == 404
    assert client.get(f"/famiglia/dipendenti/{dep.id}/modifica").status_code == 404
    assert client.get(f"/profilo/avatar/{dep.id}").status_code == 404
    assert client.post(f"/famiglia/cambia/{family.id}").status_code == 404
    html = client.get("/famiglia/").get_data(as_text=True)
    assert "Sofia" not in html and "Anna Rossi" not in html
    assert db.session.get(FamilyMember, anna_member.id) is not None


def test_role_change_keeps_at_least_one_admin(family_with_admin, make_user):
    admin, family = family_with_admin
    actor = _member(admin, family)
    with pytest.raises(ServiceError, match="almeno un amministratore"):
        family_service.change_role(actor, actor, ROLE_MEMBER)
    luca = make_user("luca@famiglia.it", "Luca")
    _, code = family_service.create_invitation(actor, ROLE_MEMBER, 3, None)
    luca_m = family_service.accept_invitation(luca, code)
    family_service.change_role(actor, luca_m, ROLE_ADMIN)
    family_service.change_role(actor, actor, ROLE_MEMBER)  # ora è possibile
    assert actor.role == ROLE_MEMBER


def test_last_admin_cannot_leave(family_with_admin, make_user):
    admin, family = family_with_admin
    actor = _member(admin, family)
    with pytest.raises(ServiceError):
        family_service.leave_family(actor)
    luca = make_user("luca@famiglia.it", "Luca")
    _, code = family_service.create_invitation(actor, ROLE_MEMBER, 3, None)
    luca_m = family_service.accept_invitation(luca, code)
    with pytest.raises(ServiceError, match="nomina un altro amministratore"):
        family_service.leave_family(actor)
    family_service.leave_family(luca_m)  # un membro può uscire
    assert family_service.membership_for(luca, family.id) is None
    assert luca.current_family_id is None


def test_dependent_profiles(client, family_with_admin, login):
    admin, family = family_with_admin
    login()
    resp = client.post("/famiglia/dipendenti/nuovo",
                       data={"display_name": "Sofia", "birth_date": "2019-05-04", "color": "#10b981"},
                       follow_redirects=True)
    assert "Profilo di Sofia creato" in resp.get_data(as_text=True)
    dep = db.session.scalar(db.select(Profile).filter_by(display_name="Sofia"))
    assert dep.is_dependent and dep.user_id is None
    assert dep.memberships[0].role == ROLE_DEPENDENT

    resp = client.post(f"/famiglia/dipendenti/{dep.id}/modifica",
                       data={"display_name": "Sofia R.", "color": "#ef4444"}, follow_redirects=True)
    assert "Profilo aggiornato" in resp.get_data(as_text=True)
    assert dep.display_name == "Sofia R."

    member_id = dep.memberships[0].id
    client.post(f"/famiglia/membri/{member_id}/rimuovi", follow_redirects=True)
    assert db.session.get(Profile, dep.id) is None  # il dipendente viene eliminato


def test_invalid_color_rejected(client, family_with_admin, login):
    login()
    resp = client.post("/famiglia/dipendenti/nuovo", data={"display_name": "Sofia", "color": "red;x"})
    assert "Colore non valido" in resp.get_data(as_text=True)
    assert db.session.scalar(db.select(Profile).filter_by(display_name="Sofia")) is None


def test_switch_between_families(client, family_with_admin, login):
    admin, family = family_with_admin
    second = family_service.create_family(admin, "Famiglia Nonni")
    assert admin.current_family_id == second.id
    login()
    resp = client.post(f"/famiglia/cambia/{family.id}", data={"next": "/famiglia/"}, follow_redirects=True)
    assert "Famiglia attiva: Famiglia Rossi" in resp.get_data(as_text=True)
    db.session.refresh(admin)
    assert admin.current_family_id == family.id


def test_delete_family_requires_exact_name(client, family_with_admin, login):
    admin, family = family_with_admin
    family_service.add_dependent(_member(admin, family), "Sofia", None, "#10b981")
    login()
    resp = client.post("/famiglia/elimina", data={"del-confirm_name": "sbagliato"}, follow_redirects=True)
    assert "non corrisponde" in resp.get_data(as_text=True)
    resp = client.post("/famiglia/elimina", data={"del-confirm_name": "Famiglia Rossi"}, follow_redirects=True)
    assert "Famiglia eliminata" in resp.get_data(as_text=True)
    assert db.session.scalar(db.select(db.func.count()).select_from(Family)) == 0
    assert db.session.scalar(db.select(Profile).filter_by(display_name="Sofia")) is None
    db.session.refresh(admin)
    assert admin.current_family_id is None and admin.profile is not None


def test_audit_log_page(client, family_with_admin, login):
    login()
    client.post("/famiglia/impostazioni", data={"name": "Rossi & Co", "submit": "1"})
    html = client.get("/famiglia/registro").get_data(as_text=True)
    assert "Famiglia rinominata" in html and "Famiglia creata" in html
