"""Catalogo della famiglia: categorie, sottocategorie, attività, indicatori e tag.

Permessi:
- creare: amministratori e membri;
- modificare / archiviare / eliminare: amministratori oppure chi ha creato l'elemento.
Un elemento già usato nelle registrazioni non si elimina: si archivia (resta nello storico).
"""
from __future__ import annotations

from decimal import Decimal

from app.extensions import db
from app.models import (
    AGGREGATION_LABELS,
    DATA_TYPE_LABELS,
    KIND_LABELS,
    ROLE_ADMIN,
    ROLE_MEMBER,
    Activity,
    ActivityEntry,
    Category,
    FamilyMember,
    MetricDefinition,
    MetricValue,
    Tag,
    entry_tags,
)
from app.services import PermissionDenied, ServiceError
from app.services.audit_service import log_action
from app.services.common import get_family_object, slugify
from app.utils.icons import ICON_NAMES


# --------------------------------------------------------------------------- permessi
def can_create(actor: FamilyMember) -> bool:
    return actor is not None and actor.role in (ROLE_ADMIN, ROLE_MEMBER)


def can_edit(actor: FamilyMember, obj) -> bool:
    if actor is None:
        return False
    if actor.is_admin:
        return True
    return getattr(obj, "created_by_user_id", None) == actor.profile.user_id


def _require_create(actor):
    if not can_create(actor):
        raise PermissionDenied("Non puoi modificare il catalogo.")


def _require_edit(actor, obj):
    if not can_edit(actor, obj):
        raise PermissionDenied("Solo un amministratore o chi l'ha creato può modificare questo elemento.")


def _check_icon(icon: str | None) -> str | None:
    if icon and icon not in ICON_NAMES:
        raise ServiceError("Icona non valida.")
    return icon or None


# --------------------------------------------------------------------------- query
def categories_tree(family_id: int, include_archived: bool = False) -> list[Category]:
    """Categorie principali (con children e activities caricate)."""
    query = db.select(Category).filter_by(family_id=family_id, parent_id=None)
    if not include_archived:
        query = query.filter_by(is_archived=False)
    return list(db.session.scalars(query.order_by(Category.sort_order, Category.name)))


def category_choices(family_id: int, top_level_only: bool = False, exclude_id: int | None = None):
    """Coppie (id, nome) per i menu a tendina, con le sottocategorie indentate."""
    choices = []
    for cat in categories_tree(family_id):
        if cat.id == exclude_id:
            continue
        choices.append((cat.id, cat.name))
        if not top_level_only:
            for sub in cat.children:
                if not sub.is_archived:
                    choices.append((sub.id, f"— {sub.name}"))
    return choices


def active_activities(family_id: int) -> list[Activity]:
    return list(
        db.session.scalars(
            db.select(Activity)
            .join(Category)
            .where(Activity.family_id == family_id, Activity.is_archived.is_(False), Category.is_archived.is_(False))
            .order_by(Activity.sort_order, Activity.name)
        )
    )


def quick_activities(family_id: int) -> list[Activity]:
    return [a for a in active_activities(family_id) if a.is_quick]


def activity_choices(family_id: int):
    return [(a.id, f"{a.category.full_name} › {a.name}") for a in active_activities(family_id)]


def tags_of(family_id: int) -> list[Tag]:
    return list(db.session.scalars(db.select(Tag).filter_by(family_id=family_id).order_by(Tag.name)))


def entry_count_for_activity(activity_id: int) -> int:
    return db.session.scalar(
        db.select(db.func.count()).select_from(ActivityEntry).filter_by(activity_id=activity_id)
    )


def value_count_for_metric(metric_id: int) -> int:
    return db.session.scalar(
        db.select(db.func.count()).select_from(MetricValue).filter_by(metric_definition_id=metric_id)
    )


def tag_usage(tag_id: int) -> int:
    return db.session.scalar(db.select(db.func.count()).select_from(entry_tags).where(entry_tags.c.tag_id == tag_id))


# --------------------------------------------------------------------------- categorie
def _validate_parent(actor, parent_id, category=None):
    if not parent_id:
        return None
    parent = get_family_object(Category, parent_id, actor.family_id)
    if parent is None or parent.parent_id is not None:
        raise ServiceError("La categoria superiore deve essere una categoria principale della famiglia.")
    if category is not None and (parent.id == category.id or category.children):
        raise ServiceError("Una categoria con sottocategorie non può diventare a sua volta sottocategoria.")
    return parent.id


def _check_category_name(actor, name, parent_id, exclude_id=None):
    query = db.select(Category).filter_by(family_id=actor.family_id, parent_id=parent_id, name=name)
    existing = db.session.scalar(query)
    if existing and existing.id != exclude_id:
        raise ServiceError("Esiste già una categoria con questo nome.")


def create_category(actor, *, name, parent_id=None, description=None, icon="tag", color="#4f46e5", sort_order=0):
    _require_create(actor)
    name = name.strip()
    parent_id = _validate_parent(actor, parent_id)
    _check_category_name(actor, name, parent_id)
    category = Category(
        family_id=actor.family_id, parent_id=parent_id, name=name, description=(description or "").strip() or None,
        icon=_check_icon(icon) or "tag", color=color.lower(), sort_order=sort_order or 0,
        created_by_user_id=actor.profile.user_id,
    )
    db.session.add(category)
    db.session.flush()
    log_action("catalog.category_created", family_id=actor.family_id, entity=category, details={"name": name})
    db.session.commit()
    return category


def update_category(actor, category, *, name, parent_id=None, description=None, icon="tag", color="#4f46e5", sort_order=0):
    _require_edit(actor, category)
    name = name.strip()
    parent_id = _validate_parent(actor, parent_id, category)
    _check_category_name(actor, name, parent_id, exclude_id=category.id)
    category.name = name
    category.parent_id = parent_id
    category.description = (description or "").strip() or None
    category.icon = _check_icon(icon) or "tag"
    category.color = color.lower()
    category.sort_order = sort_order or 0
    log_action("catalog.category_updated", family_id=actor.family_id, entity=category, details={"name": name})
    db.session.commit()


def toggle_archive_category(actor, category):
    _require_edit(actor, category)
    category.is_archived = not category.is_archived
    for sub in category.children:
        sub.is_archived = category.is_archived
    action = "catalog.category_archived" if category.is_archived else "catalog.category_restored"
    log_action(action, family_id=actor.family_id, entity=category, details={"name": category.name})
    db.session.commit()


def delete_category(actor, category):
    _require_edit(actor, category)
    if category.children or category.activities:
        raise ServiceError("La categoria contiene sottocategorie o attività: archiviala invece di eliminarla.")
    log_action("catalog.category_deleted", family_id=actor.family_id, details={"name": category.name})
    db.session.delete(category)
    db.session.commit()


# --------------------------------------------------------------------------- attività
def _activity_data(actor, data: dict, activity=None) -> dict:
    name = data["name"].strip()
    category = get_family_object(Category, data["category_id"], actor.family_id)
    if category is None:
        raise ServiceError("Categoria non valida.")
    existing = db.session.scalar(db.select(Activity).filter_by(family_id=actor.family_id, name=name))
    if existing and (activity is None or existing.id != activity.id):
        raise ServiceError("Esiste già un'attività con questo nome.")
    quantity = Decimal(str(data.get("default_quantity") or 1))
    if quantity <= 0:
        raise ServiceError("La quantità predefinita deve essere maggiore di zero.")
    if data.get("default_scope") not in ("personal", "family"):
        raise ServiceError("Ambito non valido.")
    return {
        "name": name,
        "category_id": category.id,
        "description": (data.get("description") or "").strip() or None,
        "icon": _check_icon(data.get("icon")),
        "color": data["color"].lower() if data.get("color") else None,
        "count_label": (data.get("count_label") or "volte").strip(),
        "default_quantity": quantity,
        "default_scope": data["default_scope"],
        "is_quick": bool(data.get("is_quick")),
        "sort_order": data.get("sort_order") or 0,
    }


def create_activity(actor, data: dict) -> Activity:
    _require_create(actor)
    activity = Activity(family_id=actor.family_id, created_by_user_id=actor.profile.user_id,
                        **_activity_data(actor, data))
    db.session.add(activity)
    db.session.flush()
    log_action("catalog.activity_created", family_id=actor.family_id, entity=activity, details={"name": activity.name})
    db.session.commit()
    return activity


def update_activity(actor, activity, data: dict) -> None:
    _require_edit(actor, activity)
    for key, value in _activity_data(actor, data, activity).items():
        setattr(activity, key, value)
    log_action("catalog.activity_updated", family_id=actor.family_id, entity=activity, details={"name": activity.name})
    db.session.commit()


def toggle_archive_activity(actor, activity):
    _require_edit(actor, activity)
    activity.is_archived = not activity.is_archived
    action = "catalog.activity_archived" if activity.is_archived else "catalog.activity_restored"
    log_action(action, family_id=actor.family_id, entity=activity, details={"name": activity.name})
    db.session.commit()


def delete_activity(actor, activity):
    _require_edit(actor, activity)
    if entry_count_for_activity(activity.id):
        raise ServiceError("L'attività ha delle registrazioni: archiviala per conservarne lo storico.")
    log_action("catalog.activity_deleted", family_id=actor.family_id, details={"name": activity.name})
    db.session.delete(activity)
    db.session.commit()


# --------------------------------------------------------------------------- indicatori
def _metric_data(data: dict) -> dict:
    data_type = data["data_type"]
    if data_type not in DATA_TYPE_LABELS:
        raise ServiceError("Tipo di dato non valido.")
    if data["kind"] not in KIND_LABELS or data["aggregation"] not in AGGREGATION_LABELS:
        raise ServiceError("Tipo di indicatore o aggregazione non validi.")
    min_value, max_value = data.get("min_value"), data.get("max_value")
    if min_value is not None and max_value is not None and min_value > max_value:
        raise ServiceError("Il valore minimo non può superare il massimo.")
    aggregation = data["aggregation"]
    kind = data["kind"]
    if data_type == "duration":
        kind = "duration"
    if data_type == "text":
        aggregation = "sum"  # irrilevante per i testi
        min_value = max_value = None
    if data_type == "boolean":
        min_value = max_value = None
    return {
        "name": data["name"].strip(),
        "data_type": data_type,
        "unit": (data.get("unit") or "").strip() or None,
        "kind": kind,
        "aggregation": aggregation,
        "min_value": min_value,
        "max_value": max_value,
        "is_required": bool(data.get("is_required")),
        "sort_order": data.get("sort_order") or 0,
    }


def _unique_key(activity, name, exclude_id=None) -> str:
    base = slugify(name)
    keys = {m.key for m in activity.metrics if m.id != exclude_id}
    key, n = base, 2
    while key in keys:
        key = f"{base[:36]}_{n}"
        n += 1
    return key


def add_metric(actor, activity, data: dict) -> MetricDefinition:
    _require_edit(actor, activity)
    values = _metric_data(data)
    if any(m.name.lower() == values["name"].lower() for m in activity.metrics):
        raise ServiceError("Questa attività ha già un indicatore con questo nome.")
    metric = MetricDefinition(activity_id=activity.id, key=_unique_key(activity, values["name"]), **values)
    db.session.add(metric)
    db.session.flush()
    log_action("catalog.metric_created", family_id=actor.family_id, entity=metric,
               details={"activity": activity.name, "name": metric.name})
    db.session.commit()
    return metric


def update_metric(actor, metric, data: dict) -> None:
    _require_edit(actor, metric.activity)
    values = _metric_data(data)
    if values["data_type"] != metric.data_type and value_count_for_metric(metric.id):
        raise ServiceError("Il tipo di dato non si può cambiare: l'indicatore ha già dei valori registrati.")
    if any(m.name.lower() == values["name"].lower() and m.id != metric.id for m in metric.activity.metrics):
        raise ServiceError("Questa attività ha già un indicatore con questo nome.")
    for key, value in values.items():
        setattr(metric, key, value)
    log_action("catalog.metric_updated", family_id=actor.family_id, entity=metric,
               details={"activity": metric.activity.name, "name": metric.name})
    db.session.commit()


def toggle_archive_metric(actor, metric):
    _require_edit(actor, metric.activity)
    metric.is_archived = not metric.is_archived
    db.session.commit()


def delete_metric(actor, metric):
    _require_edit(actor, metric.activity)
    if value_count_for_metric(metric.id):
        raise ServiceError("L'indicatore ha dei valori registrati: archivialo per conservarli.")
    log_action("catalog.metric_deleted", family_id=actor.family_id,
               details={"activity": metric.activity.name, "name": metric.name})
    db.session.delete(metric)
    db.session.commit()


def get_family_metric(metric_id: int, family_id: int) -> MetricDefinition | None:
    return db.session.scalar(
        db.select(MetricDefinition).join(Activity).where(MetricDefinition.id == metric_id, Activity.family_id == family_id)
    )


# --------------------------------------------------------------------------- tag
def _check_tag_name(actor, name, exclude_id=None):
    existing = db.session.scalar(db.select(Tag).filter_by(family_id=actor.family_id, name=name))
    if existing and existing.id != exclude_id:
        raise ServiceError("Esiste già un tag con questo nome.")


def create_tag(actor, name: str, color: str = "#64748b") -> Tag:
    _require_create(actor)
    name = name.strip().lstrip("#")
    if not name:
        raise ServiceError("Il nome del tag è obbligatorio.")
    _check_tag_name(actor, name)
    tag = Tag(family_id=actor.family_id, name=name, color=color.lower())
    db.session.add(tag)
    db.session.commit()
    return tag


def get_or_create_tags(actor, names: list[str]) -> list[Tag]:
    """Usato dal form di registrazione: tag nuovi scritti a mano vengono creati al volo."""
    result = []
    for raw in names:
        name = raw.strip().lstrip("#")[:40]
        if not name:
            continue
        tag = db.session.scalar(db.select(Tag).filter_by(family_id=actor.family_id, name=name))
        if tag is None:
            tag = Tag(family_id=actor.family_id, name=name)
            db.session.add(tag)
            db.session.flush()
        if tag not in result:
            result.append(tag)
    return result


def update_tag(actor, tag, name: str, color: str) -> None:
    _require_create(actor)
    name = name.strip().lstrip("#")
    _check_tag_name(actor, name, exclude_id=tag.id)
    tag.name = name
    tag.color = color.lower()
    db.session.commit()


def delete_tag(actor, tag) -> None:
    if not actor.is_admin:
        raise PermissionDenied("Solo gli amministratori possono eliminare i tag.")
    log_action("catalog.tag_deleted", family_id=actor.family_id, details={"name": tag.name})
    db.session.delete(tag)
    db.session.commit()
