"""Registrazioni delle attività: modalità rapida "+1", modalità completa, storico, allegati.

Regole di visibilità (applicate in TUTTE le letture, statistiche comprese):
- registrazione "familiare" (visibility = family): visibile a tutta la famiglia;
- registrazione "privata": visibile solo a chi l'ha inserita e a chi l'ha svolta.

Chi può registrare per conto di chi:
- ognuno per sé e per i profili dipendenti;
- gli amministratori anche per gli altri membri.

Chi può modificare/eliminare: chi l'ha inserita, chi l'ha svolta, gli amministratori
(se la registrazione è visibile a loro).
"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from flask import current_app
from sqlalchemy import or_
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models import (
    ROLE_DEPENDENT,
    SCOPE_FAMILY,
    VISIBILITY_FAMILY,
    VISIBILITY_PRIVATE,
    Activity,
    ActivityEntry,
    Attachment,
    EntryRevision,
    FamilyMember,
    MetricValue,
    Profile,
    Tag,
)
from app.services import PermissionDenied, ServiceError
from app.services.audit_service import log_action
from app.services.common import get_family_object
from app.utils.formatting import fmt_duration, fmt_number, parse_decimal, parse_duration
from app.utils.timezone import to_local, utcnow
from app.utils.uploads import delete_upload, save_image, upload_dir

ATTACHMENT_DIR = "attachments"
MAX_ATTACHMENTS_PER_ENTRY = 10
ATTACHMENT_IMAGE_SIZE = 1600
ALLOWED_ATTACHMENT_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif", "pdf"}


class EntryValidationError(ServiceError):
    """Errori di validazione legati a campi specifici del form: {nome_campo: messaggio}."""

    def __init__(self, errors: dict[str, str]):
        super().__init__("Controlla i campi evidenziati.")
        self.errors = errors


@dataclass
class EntryData:
    activity_id: int
    performed_by_profile_id: int
    occurred_at: datetime  # UTC naive
    quantity: Decimal
    scope: str
    visibility: str
    description: str | None = None
    notes: str | None = None
    tag_ids: list[int] = field(default_factory=list)
    new_tags: list[str] = field(default_factory=list)
    participant_ids: list[int] = field(default_factory=list)
    metric_inputs: dict[int, object] = field(default_factory=dict)  # metric_id -> testo/bool dal form


# --------------------------------------------------------------------------- permessi e query
def performer_choices(actor: FamilyMember) -> list[Profile]:
    """Profili per cui l'utente può registrare un'attività."""
    members = db.session.scalars(
        db.select(FamilyMember).join(Profile).where(FamilyMember.family_id == actor.family_id)
        .order_by(Profile.display_name)
    )
    result = [actor.profile]
    for m in members:
        if m.profile_id == actor.profile_id:
            continue
        if actor.is_admin or m.role == ROLE_DEPENDENT:
            result.append(m.profile)
    return result


def family_profiles(family_id: int) -> list[Profile]:
    return list(
        db.session.scalars(
            db.select(Profile).join(FamilyMember).where(FamilyMember.family_id == family_id)
            .order_by(Profile.display_name)
        )
    )


def visibility_clause(actor: FamilyMember):
    """Condizione SQL: registrazioni della famiglia attiva visibili all'utente."""
    return db.and_(
        ActivityEntry.family_id == actor.family_id,
        or_(
            ActivityEntry.visibility == VISIBILITY_FAMILY,
            ActivityEntry.created_by_user_id == actor.profile.user_id,
            ActivityEntry.performed_by_profile_id == actor.profile_id,
        ),
    )


def get_visible_entry(actor: FamilyMember, entry_id: int, include_deleted: bool = False) -> ActivityEntry | None:
    query = db.select(ActivityEntry).where(ActivityEntry.id == entry_id, visibility_clause(actor))
    if not include_deleted:
        query = query.where(ActivityEntry.deleted_at.is_(None))
    return db.session.scalar(query)


def can_edit(actor: FamilyMember, entry: ActivityEntry) -> bool:
    return (
        actor.is_admin
        or entry.created_by_user_id == actor.profile.user_id
        or entry.performed_by_profile_id == actor.profile_id
    )


def _require_edit(actor, entry):
    if not can_edit(actor, entry):
        raise PermissionDenied("Non puoi modificare questa registrazione.")


@dataclass
class EntryFilters:
    profile_id: int | None = None
    category_id: int | None = None
    activity_id: int | None = None
    tag_id: int | None = None
    scope: str | None = None
    date_from: datetime | None = None  # UTC
    date_to: datetime | None = None  # UTC (escluso)
    text: str | None = None
    deleted: bool = False


def filtered_query(actor: FamilyMember, filters: EntryFilters):
    query = (
        db.select(ActivityEntry)
        .join(Activity, ActivityEntry.activity_id == Activity.id)
        .where(visibility_clause(actor))
        .options(
            selectinload(ActivityEntry.activity).selectinload(Activity.category),
            selectinload(ActivityEntry.performed_by),
            selectinload(ActivityEntry.tags),
            selectinload(ActivityEntry.metric_values).selectinload(MetricValue.definition),
        )
    )
    query = query.where(
        ActivityEntry.deleted_at.is_not(None) if filters.deleted else ActivityEntry.deleted_at.is_(None)
    )
    if filters.profile_id:
        query = query.where(
            or_(
                ActivityEntry.performed_by_profile_id == filters.profile_id,
                ActivityEntry.participants.any(Profile.id == filters.profile_id),
            )
        )
    if filters.activity_id:
        query = query.where(ActivityEntry.activity_id == filters.activity_id)
    if filters.category_id:
        from app.models import Category

        sub_ids = db.select(Category.id).where(
            or_(Category.id == filters.category_id, Category.parent_id == filters.category_id)
        )
        query = query.where(Activity.category_id.in_(sub_ids))
    if filters.tag_id:
        query = query.where(ActivityEntry.tags.any(Tag.id == filters.tag_id))
    if filters.scope in ("personal", "family"):
        query = query.where(ActivityEntry.scope == filters.scope)
    if filters.date_from:
        query = query.where(ActivityEntry.occurred_at >= filters.date_from)
    if filters.date_to:
        query = query.where(ActivityEntry.occurred_at < filters.date_to)
    if filters.text:
        like = f"%{filters.text}%"
        query = query.where(or_(ActivityEntry.description.ilike(like), ActivityEntry.notes.ilike(like),
                                Activity.name.ilike(like)))
    return query.order_by(ActivityEntry.occurred_at.desc(), ActivityEntry.id.desc())


def recent_entries(actor: FamilyMember, limit: int = 8) -> list[ActivityEntry]:
    return list(db.session.scalars(filtered_query(actor, EntryFilters()).limit(limit)))


# --------------------------------------------------------------------------- valori indicatori
def parse_metric_input(metric, raw) -> tuple[Decimal | None, str | None]:
    """Converte l'input del form nel valore da salvare. Solleva ValueError con messaggio leggibile."""
    if metric.data_type == "boolean":
        return (Decimal(1) if raw else Decimal(0)), None
    text = ("" if raw is None else str(raw)).strip()
    if text == "":
        if metric.is_required:
            raise ValueError("Campo obbligatorio.")
        return None, None
    if metric.data_type == "text":
        return None, text[:500]
    if metric.data_type == "duration":
        value = Decimal(parse_duration(text))
    else:
        value = parse_decimal(text)
        if metric.data_type == "integer" and value != value.to_integral_value():
            raise ValueError("Inserisci un numero intero.")
    compare = value / 60 if metric.data_type == "duration" else value  # min/max della durata in minuti
    if metric.min_value is not None and compare < metric.min_value:
        raise ValueError(f"Il valore minimo è {fmt_number(metric.min_value)}.")
    if metric.max_value is not None and compare > metric.max_value:
        raise ValueError(f"Il valore massimo è {fmt_number(metric.max_value)}.")
    return value, None


def format_metric_value(value: MetricValue) -> str:
    metric = value.definition
    if metric.data_type == "text":
        return value.value_text or ""
    if value.value_numeric is None:
        return ""
    if metric.data_type == "boolean":
        return "Sì" if value.value_numeric else "No"
    if metric.data_type == "duration":
        return fmt_duration(value.value_numeric)
    unit = f" {metric.unit}" if metric.unit else ""
    return f"{fmt_number(value.value_numeric)}{unit}"


def metric_input_value(value: MetricValue | None):
    """Valore da precompilare nel form di modifica."""
    if value is None:
        return None
    metric = value.definition
    if metric.data_type == "text":
        return value.value_text
    if metric.data_type == "boolean":
        return bool(value.value_numeric)
    if metric.data_type == "duration":
        return fmt_duration(value.value_numeric)
    return fmt_number(value.value_numeric, 4).replace(".", "")


# --------------------------------------------------------------------------- storico
def snapshot(entry: ActivityEntry) -> dict:
    local = to_local(entry.occurred_at)
    return {
        "Attività": entry.activity.name,
        "Svolta da": entry.performed_by.display_name,
        "Data e ora": local.strftime("%d/%m/%Y %H:%M"),
        "Quantità": f"{fmt_number(entry.quantity)} {entry.activity.count_label}",
        "Ambito": "Familiare" if entry.scope == SCOPE_FAMILY else "Personale",
        "Visibilità": "Famiglia" if entry.visibility == VISIBILITY_FAMILY else "Privata",
        "Descrizione": entry.description or "",
        "Note": entry.notes or "",
        "Tag": ", ".join(sorted(t.name for t in entry.tags)),
        "Partecipanti": ", ".join(sorted(p.display_name for p in entry.participants)),
        **{v.definition.name: format_metric_value(v) for v in entry.metric_values},
        "Allegati": str(len(entry.attachments)),
    }


def _add_revision(entry: ActivityEntry, action: str, user_id: int | None) -> None:
    db.session.flush()
    db.session.refresh(entry)
    db.session.add(EntryRevision(
        entry_id=entry.id, changed_by_user_id=user_id, action=action,
        snapshot_json=json.dumps(snapshot(entry), ensure_ascii=False),
    ))


def revision_history(entry: ActivityEntry) -> list[dict]:
    """Revisioni dalla più recente con l'elenco dei campi cambiati rispetto alla precedente."""
    revisions = list(reversed(entry.revisions))  # dalla più vecchia
    history, previous = [], {}
    for rev in revisions:
        current = rev.snapshot
        changes = [
            (key, previous.get(key, ""), current.get(key, ""))
            for key in dict.fromkeys(list(previous) + list(current))
            if previous.get(key, "") != current.get(key, "")
        ] if rev.action == "update" else []
        history.append({"revision": rev, "changes": changes})
        previous = current
    return list(reversed(history))


# --------------------------------------------------------------------------- salvataggio
def _validate(actor: FamilyMember, data: EntryData) -> tuple[Activity, dict]:
    errors: dict[str, str] = {}
    activity = get_family_object(Activity, data.activity_id, actor.family_id)
    if activity is None or activity.is_archived:
        raise EntryValidationError({"activity_id": "Attività non valida."})
    if data.performed_by_profile_id not in {p.id for p in performer_choices(actor)}:
        errors["performed_by_profile_id"] = "Non puoi registrare attività per questa persona."
    if data.quantity is None or data.quantity <= 0:
        errors["quantity"] = "La quantità deve essere maggiore di zero."
    if data.scope not in ("personal", "family"):
        errors["scope"] = "Ambito non valido."
    if data.visibility not in (VISIBILITY_PRIVATE, VISIBILITY_FAMILY):
        errors["visibility"] = "Visibilità non valida."
    if data.occurred_at > utcnow() + timedelta(days=366):
        errors["occurred_at"] = "Data troppo lontana nel futuro."
    family_ids = {p.id for p in family_profiles(actor.family_id)}
    if not set(data.participant_ids) <= family_ids:
        errors["participant_ids"] = "Partecipanti non validi."
    valid_tags = {t.id for t in db.session.scalars(db.select(Tag).filter_by(family_id=actor.family_id))}
    if not set(data.tag_ids) <= valid_tags:
        errors["tag_ids"] = "Tag non validi."
    parsed = {}
    for metric in activity.active_metrics:
        try:
            parsed[metric.id] = parse_metric_input(metric, data.metric_inputs.get(metric.id))
        except ValueError as exc:
            errors[f"m_{metric.id}"] = str(exc)
    if errors:
        raise EntryValidationError(errors)
    return activity, parsed


def _apply(actor, entry: ActivityEntry, data: EntryData, activity: Activity, parsed: dict) -> None:
    from app.services import catalog_service

    entry.activity_id = activity.id
    entry.performed_by_profile_id = data.performed_by_profile_id
    entry.occurred_at = data.occurred_at
    entry.quantity = data.quantity
    entry.scope = data.scope
    entry.visibility = data.visibility
    entry.description = (data.description or "").strip() or None
    entry.notes = (data.notes or "").strip() or None
    tags = list(db.session.scalars(db.select(Tag).where(Tag.family_id == actor.family_id, Tag.id.in_(data.tag_ids))))
    for tag in catalog_service.get_or_create_tags(actor, data.new_tags):
        if tag not in tags:
            tags.append(tag)
    entry.tags = tags
    entry.participants = list(db.session.scalars(db.select(Profile).where(Profile.id.in_(data.participant_ids))))
    existing = {v.metric_definition_id: v for v in entry.metric_values}
    for metric_id, (numeric, text) in parsed.items():
        value = existing.get(metric_id)
        if numeric is None and text is None:
            if value is not None:
                entry.metric_values.remove(value)
            continue
        if value is None:
            value = MetricValue(metric_definition_id=metric_id)
            entry.metric_values.append(value)
        value.value_numeric, value.value_text = numeric, text


def quick_add(actor: FamilyMember, activity_id: int, performed_by_profile_id: int | None = None) -> ActivityEntry:
    """Modalità rapida: +1 (quantità predefinita), adesso, per me o per il profilo scelto."""
    activity = get_family_object(Activity, activity_id, actor.family_id)
    if activity is None or activity.is_archived:
        raise ServiceError("Attività non disponibile.")
    performer_id = performed_by_profile_id or actor.profile_id
    if performer_id not in {p.id for p in performer_choices(actor)}:
        raise PermissionDenied("Non puoi registrare attività per questa persona.")
    entry = ActivityEntry(
        family_id=actor.family_id, activity_id=activity.id, performed_by_profile_id=performer_id,
        created_by_user_id=actor.profile.user_id, occurred_at=utcnow(), quantity=activity.default_quantity,
        scope=activity.default_scope, visibility=VISIBILITY_FAMILY,
    )
    db.session.add(entry)
    _add_revision(entry, "create", actor.profile.user_id)
    db.session.commit()
    _after_change(actor, entry)
    return entry


def create_entry(actor: FamilyMember, data: EntryData, files=None) -> ActivityEntry:
    activity, parsed = _validate(actor, data)
    entry = ActivityEntry(family_id=actor.family_id, created_by_user_id=actor.profile.user_id)
    db.session.add(entry)
    _apply(actor, entry, data, activity, parsed)
    db.session.flush()
    saved_files = _store_attachments(actor, entry, files or [])
    try:
        _add_revision(entry, "create", actor.profile.user_id)
        db.session.commit()
    except Exception:
        db.session.rollback()
        for name in saved_files:
            delete_upload(ATTACHMENT_DIR, name)
        raise
    _after_change(actor, entry)
    return entry


def update_entry(actor: FamilyMember, entry: ActivityEntry, data: EntryData, files=None) -> None:
    _require_edit(actor, entry)
    activity, parsed = _validate(actor, data)
    if activity.id != entry.activity_id:
        # cambiando attività, i valori degli indicatori della vecchia attività non hanno più senso
        entry.metric_values = [v for v in entry.metric_values if v.definition.activity_id == activity.id]
    _apply(actor, entry, data, activity, parsed)
    _store_attachments(actor, entry, files or [])
    _add_revision(entry, "update", actor.profile.user_id)
    db.session.commit()
    _after_change(actor, entry)


def delete_entry(actor: FamilyMember, entry: ActivityEntry) -> None:
    _require_edit(actor, entry)
    entry.deleted_at = utcnow()
    _add_revision(entry, "delete", actor.profile.user_id)
    log_action("entry.deleted", family_id=actor.family_id, entity=entry, details={"activity": entry.activity.name})
    db.session.commit()
    _after_change(actor, entry)


def restore_entry(actor: FamilyMember, entry: ActivityEntry) -> None:
    _require_edit(actor, entry)
    entry.deleted_at = None
    _add_revision(entry, "restore", actor.profile.user_id)
    log_action("entry.restored", family_id=actor.family_id, entity=entry, details={"activity": entry.activity.name})
    db.session.commit()
    _after_change(actor, entry)


def purge_entry(actor: FamilyMember, entry: ActivityEntry) -> None:
    """Eliminazione definitiva (solo amministratori, solo dal cestino)."""
    if not actor.is_admin or entry.deleted_at is None:
        raise PermissionDenied("Solo gli amministratori possono svuotare il cestino.")
    files = [a.stored_filename for a in entry.attachments]
    log_action("entry.purged", family_id=actor.family_id, details={"activity": entry.activity.name, "id": entry.id})
    db.session.delete(entry)
    db.session.commit()
    for name in files:
        delete_upload(ATTACHMENT_DIR, name)


def _after_change(actor: FamilyMember, entry: ActivityEntry) -> None:
    """Dopo ogni modifica: ricalcolo degli obiettivi coinvolti (notifiche di traguardo)."""
    try:
        from app.services import goal_service
    except ImportError:  # pragma: no cover
        return
    goal_service.evaluate_family_goals(actor.family_id)


# --------------------------------------------------------------------------- allegati
def _store_attachments(actor, entry: ActivityEntry, files) -> list[str]:
    files = [f for f in files if f and f.filename]
    if not files:
        return []
    if len(entry.attachments) + len(files) > MAX_ATTACHMENTS_PER_ENTRY:
        raise EntryValidationError({"attachments": f"Massimo {MAX_ATTACHMENTS_PER_ENTRY} allegati per registrazione."})
    saved = []
    try:
        for file in files:
            ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
            if ext not in ALLOWED_ATTACHMENT_EXTENSIONS:
                raise EntryValidationError({"attachments": f"Formato non consentito: {file.filename}"})
            if ext == "pdf":
                head = file.stream.read(5)
                file.stream.seek(0)
                if head != b"%PDF-":
                    raise EntryValidationError({"attachments": f"{file.filename} non è un PDF valido."})
                name = f"{uuid.uuid4().hex}.pdf"
                path = os.path.join(upload_dir(ATTACHMENT_DIR), name)
                file.save(path)
                mime = "application/pdf"
            else:
                try:
                    name = save_image(file, ATTACHMENT_DIR, ATTACHMENT_IMAGE_SIZE)
                except ServiceError as exc:
                    raise EntryValidationError({"attachments": f"{file.filename}: {exc}"}) from exc
                mime = "image/webp"
            saved.append(name)
            size = os.path.getsize(os.path.join(upload_dir(ATTACHMENT_DIR), name))
            entry.attachments.append(Attachment(
                family_id=actor.family_id, stored_filename=name, original_filename=os.path.basename(file.filename)[:255],
                mime_type=mime, size_bytes=size, uploaded_by_user_id=actor.profile.user_id,
            ))
    except Exception:
        for name in saved:
            delete_upload(ATTACHMENT_DIR, name)
        raise
    return saved


def delete_attachment(actor: FamilyMember, attachment: Attachment) -> None:
    entry = attachment.entry
    _require_edit(actor, entry)
    name = attachment.stored_filename
    entry.attachments.remove(attachment)
    _add_revision(entry, "update", actor.profile.user_id)
    db.session.commit()
    delete_upload(ATTACHMENT_DIR, name)


def attachment_path(attachment: Attachment) -> tuple[str, str]:
    return upload_dir(ATTACHMENT_DIR), attachment.stored_filename


def count_for_profile(profile_id: int) -> int:
    return db.session.scalar(
        db.select(db.func.count()).select_from(ActivityEntry).filter_by(performed_by_profile_id=profile_id)
    )


def max_upload_mb() -> int:
    return current_app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)
