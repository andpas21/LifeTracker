"""Helper comuni ai servizi."""
from __future__ import annotations

import re
import unicodedata

from flask import abort

from app.extensions import db


def get_family_object(model, obj_id: int, family_id: int):
    """Restituisce l'oggetto solo se appartiene alla famiglia indicata, altrimenti None."""
    if obj_id is None:
        return None
    return db.session.scalar(db.select(model).filter_by(id=obj_id, family_id=family_id))


def get_family_object_or_404(model, obj_id: int, family_id: int):
    obj = get_family_object(model, obj_id, family_id)
    if obj is None:
        abort(404)
    return obj


def slugify(text: str, max_length: int = 40) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return (text or "valore")[:max_length]
