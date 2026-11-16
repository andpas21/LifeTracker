"""Famiglie, membri, ruoli, inviti e profili dipendenti.

Tutte le funzioni che modificano dati ricevono l'`actor` (FamilyMember di chi
esegue l'operazione) e ne verificano i permessi: le route non sono l'unico controllo.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import date, timedelta

from app.extensions import db
from app.models import (
    ROLE_ADMIN,
    ROLE_DEPENDENT,
    ROLE_MEMBER,
    Family,
    FamilyInvitation,
    FamilyMember,
    Profile,
    User,
)
from app.services import PermissionDenied, ServiceError
from app.services.audit_service import log_action
from app.utils.timezone import utcnow
from app.utils.uploads import delete_upload

INVITE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # niente 0/O, 1/I: codici facili da dettare
INVITE_LENGTH = 10


# --------------------------------------------------------------------------- query
def memberships_of(user: User) -> list[FamilyMember]:
    if user.profile is None:
        return []
    return list(
        db.session.scalars(
            db.select(FamilyMember)
            .join(Family)
            .where(FamilyMember.profile_id == user.profile.id)
            .order_by(Family.name)
        )
    )


def membership_for(user: User, family_id: int) -> FamilyMember | None:
    if user.profile is None:
        return None
    return db.session.scalar(
        db.select(FamilyMember).filter_by(family_id=family_id, profile_id=user.profile.id)
    )


def resolve_current_membership(user: User) -> FamilyMember | None:
    """Membership nella famiglia attiva; se non valida passa alla prima famiglia disponibile."""
    if user.current_family_id:
        membership = membership_for(user, user.current_family_id)
        if membership:
            return membership
    memberships = memberships_of(user)
    new_id = memberships[0].family_id if memberships else None
    if user.current_family_id != new_id:
        user.current_family_id = new_id
        db.session.commit()
    return memberships[0] if memberships else None


def family_members(family: Family) -> list[FamilyMember]:
    """Membri ordinati: prima amministratori, poi membri, poi dipendenti; poi per nome."""
    order = {ROLE_ADMIN: 0, ROLE_MEMBER: 1, ROLE_DEPENDENT: 2}
    members = list(
        db.session.scalars(
            db.select(FamilyMember).join(Profile).where(FamilyMember.family_id == family.id)
        )
    )
    return sorted(members, key=lambda m: (order.get(m.role, 9), m.profile.display_name.lower()))


def get_member_or_none(family: Family, member_id: int) -> FamilyMember | None:
    """Cerca un membro *solo* dentro la famiglia indicata (isolamento tra famiglie)."""
    return db.session.scalar(db.select(FamilyMember).filter_by(id=member_id, family_id=family.id))


def get_dependent_or_none(family: Family, profile_id: int) -> FamilyMember | None:
    return db.session.scalar(
        db.select(FamilyMember).filter_by(
            family_id=family.id, profile_id=profile_id, role=ROLE_DEPENDENT
        )
    )


def shares_family(user: User, profile_id: int) -> bool:
    """True se il profilo indicato appartiene ad almeno una famiglia dell'utente."""
    if user.profile is None:
        return False
    if user.profile.id == profile_id:
        return True
    mine = db.select(FamilyMember.family_id).where(FamilyMember.profile_id == user.profile.id)
    return (
        db.session.scalar(
            db.select(db.func.count())
            .select_from(FamilyMember)
            .where(FamilyMember.profile_id == profile_id, FamilyMember.family_id.in_(mine))
        )
        > 0
    )


def admin_count(family: Family) -> int:
    return db.session.scalar(
        db.select(db.func.count()).select_from(FamilyMember).filter_by(family_id=family.id, role=ROLE_ADMIN)
    )


def _require_admin(actor: FamilyMember) -> None:
    if actor is None or not actor.is_admin:
        raise PermissionDenied("Operazione riservata agli amministratori della famiglia.")


# --------------------------------------------------------------------------- famiglie
def create_family(user: User, name: str) -> Family:
    name = (name or "").strip()
    if not name:
        raise ServiceError("Il nome della famiglia è obbligatorio.")
    family = Family(name=name, created_by_user_id=user.id)
    db.session.add(family)
    db.session.flush()
    db.session.add(FamilyMember(family_id=family.id, profile_id=user.profile.id, role=ROLE_ADMIN))
    user.current_family_id = family.id
    log_action("family.created", family_id=family.id, entity=family, details={"name": name})
    db.session.commit()
    return family


def switch_family(user: User, family_id: int) -> Family:
    membership = membership_for(user, family_id)
    if membership is None:
        raise PermissionDenied("Non fai parte di questa famiglia.")
    user.current_family_id = family_id
    db.session.commit()
    return membership.family


def rename_family(actor: FamilyMember, name: str) -> None:
    _require_admin(actor)
    name = (name or "").strip()
    if not name:
        raise ServiceError("Il nome della famiglia è obbligatorio.")
    old = actor.family.name
    actor.family.name = name
    log_action(
        "family.renamed", family_id=actor.family_id, entity=actor.family, details={"from": old, "to": name}
    )
    db.session.commit()


def delete_family(actor: FamilyMember, confirm_name: str) -> None:
    """Elimina la famiglia e i suoi profili dipendenti. Richiede di digitare il nome esatto."""
    _require_admin(actor)
    family = actor.family
    if (confirm_name or "").strip() != family.name:
        raise ServiceError("Il nome inserito non corrisponde: famiglia non eliminata.")
    # Un dipendente appartiene a una sola famiglia: viene eliminato insieme alla famiglia.
    dependents = [
        (m.profile_id, m.profile.avatar_filename)
        for m in family.memberships
        if m.role == ROLE_DEPENDENT and len(m.profile.memberships) <= 1
    ]
    log_action("family.deleted", details={"family_id": family.id, "name": family.name})
    db.session.execute(
        db.update(User).where(User.current_family_id == family.id).values(current_family_id=None)
    )
    db.session.delete(family)  # le appartenenze e gli inviti vengono eliminati a cascata
    db.session.flush()
    if dependents:
        db.session.execute(db.delete(Profile).where(Profile.id.in_([pid for pid, _ in dependents])))
    db.session.commit()
    for _, avatar_filename in dependents:
        delete_upload("avatars", avatar_filename)


def leave_family(actor: FamilyMember) -> None:
    family = actor.family
    if actor.is_admin and admin_count(family) <= 1:
        others = [m for m in family.memberships if m.id != actor.id and m.role != ROLE_DEPENDENT]
        if others:
            raise ServiceError(
                "Sei l'unico amministratore: nomina un altro amministratore prima di lasciare la famiglia."
            )
        raise ServiceError(
            "Sei l'unico componente con un account: per chiudere la famiglia usa 'Elimina famiglia'."
        )
    log_action("family.member_left", family_id=family.id, entity=actor)
    user = actor.profile.user
    db.session.delete(actor)
    if user and user.current_family_id == family.id:
        user.current_family_id = None
    db.session.commit()


# --------------------------------------------------------------------------- membri
def change_role(actor: FamilyMember, member: FamilyMember, new_role: str) -> None:
    _require_admin(actor)
    if member.family_id != actor.family_id:
        raise PermissionDenied("Membro non trovato.")
    if member.role == ROLE_DEPENDENT or new_role not in (ROLE_ADMIN, ROLE_MEMBER):
        raise ServiceError("Ruolo non valido per questo componente.")
    if member.role == ROLE_ADMIN and new_role != ROLE_ADMIN and admin_count(member.family) <= 1:
        raise ServiceError("La famiglia deve avere almeno un amministratore.")
    old = member.role
    member.role = new_role
    log_action(
        "family.member_role_changed",
        family_id=member.family_id,
        entity=member,
        details={"profile": member.profile.display_name, "from": old, "to": new_role},
    )
    db.session.commit()


def remove_member(actor: FamilyMember, member: FamilyMember) -> None:
    _require_admin(actor)
    if member.family_id != actor.family_id:
        raise PermissionDenied("Membro non trovato.")
    if member.id == actor.id:
        raise ServiceError("Per uscire dalla famiglia usa 'Lascia la famiglia'.")
    if member.role == ROLE_ADMIN and admin_count(member.family) <= 1:
        raise ServiceError("La famiglia deve avere almeno un amministratore.")
    details = {"profile": member.profile.display_name, "role": member.role}
    profile = member.profile
    log_action("family.member_removed", family_id=member.family_id, entity=member, details=details)
    db.session.delete(member)
    if profile.is_dependent and len(profile.memberships) <= 1:
        delete_upload("avatars", profile.avatar_filename)
        db.session.delete(profile)
    elif profile.user and profile.user.current_family_id == actor.family_id:
        profile.user.current_family_id = None
    db.session.commit()


# --------------------------------------------------------------------------- dipendenti
def add_dependent(
    actor: FamilyMember, display_name: str, birth_date: date | None, color: str, bio: str | None = None
) -> Profile:
    _require_admin(actor)
    profile = Profile(
        display_name=display_name.strip(), birth_date=birth_date, color=color, bio=(bio or None)
    )
    db.session.add(profile)
    db.session.flush()
    db.session.add(FamilyMember(family_id=actor.family_id, profile_id=profile.id, role=ROLE_DEPENDENT))
    log_action(
        "family.dependent_added", family_id=actor.family_id, entity=profile, details={"name": profile.display_name}
    )
    db.session.commit()
    return profile


# --------------------------------------------------------------------------- inviti
def _hash_code(code: str) -> str:
    normalized = "".join(ch for ch in (code or "").upper() if ch.isalnum())
    return hashlib.sha256(normalized.encode()).hexdigest()


def format_code(code: str) -> str:
    return f"{code[:5]}-{code[5:]}"


def create_invitation(actor: FamilyMember, role: str, valid_days: int, note: str | None) -> tuple[FamilyInvitation, str]:
    """Crea un invito e restituisce (invito, codice in chiaro). Il codice non viene salvato."""
    _require_admin(actor)
    if role not in (ROLE_ADMIN, ROLE_MEMBER):
        raise ServiceError("Ruolo non valido.")
    if not 1 <= valid_days <= 30:
        raise ServiceError("La validità deve essere tra 1 e 30 giorni.")
    code = "".join(secrets.choice(INVITE_ALPHABET) for _ in range(INVITE_LENGTH))
    invitation = FamilyInvitation(
        family_id=actor.family_id,
        code_hash=_hash_code(code),
        role=role,
        note=(note or "").strip() or None,
        created_by_user_id=actor.profile.user_id,
        expires_at=utcnow() + timedelta(days=valid_days),
    )
    db.session.add(invitation)
    db.session.flush()
    log_action(
        "family.invitation_created",
        family_id=actor.family_id,
        entity=invitation,
        details={"role": role, "days": valid_days, "note": invitation.note},
    )
    db.session.commit()
    return invitation, format_code(code)


def list_invitations(family: Family) -> list[FamilyInvitation]:
    return list(
        db.session.scalars(
            db.select(FamilyInvitation)
            .filter_by(family_id=family.id)
            .order_by(FamilyInvitation.created_at.desc())
        )
    )


def find_valid_invitation(code: str) -> FamilyInvitation | None:
    invitation = db.session.scalar(db.select(FamilyInvitation).filter_by(code_hash=_hash_code(code)))
    if invitation is None or invitation.status != "pending":
        return None
    return invitation


def accept_invitation(user: User, code: str) -> FamilyMember:
    invitation = find_valid_invitation(code)
    if invitation is None:
        raise ServiceError("Codice d'invito non valido, scaduto o già utilizzato.")
    if membership_for(user, invitation.family_id):
        raise ServiceError("Fai già parte di questa famiglia.")
    membership = FamilyMember(family_id=invitation.family_id, profile_id=user.profile.id, role=invitation.role)
    db.session.add(membership)
    invitation.accepted_at = utcnow()
    invitation.accepted_by_user_id = user.id
    user.current_family_id = invitation.family_id
    db.session.flush()
    log_action(
        "family.member_joined",
        family_id=invitation.family_id,
        entity=membership,
        details={"profile": user.profile.display_name, "role": invitation.role},
    )
    db.session.commit()
    return membership


def revoke_invitation(actor: FamilyMember, invitation_id: int) -> None:
    _require_admin(actor)
    invitation = db.session.scalar(
        db.select(FamilyInvitation).filter_by(id=invitation_id, family_id=actor.family_id)
    )
    if invitation is None:
        raise PermissionDenied("Invito non trovato.")
    if invitation.status != "pending":
        raise ServiceError("L'invito non è più attivo.")
    invitation.revoked_at = utcnow()
    log_action("family.invitation_revoked", family_id=actor.family_id, entity=invitation)
    db.session.commit()
