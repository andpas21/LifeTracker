"""Upload sicuro delle immagini.

Difese applicate:
- estensione consentita (lista bianca);
- dimensione massima (MAX_CONTENT_LENGTH di Flask → errore 413);
- il file viene aperto e verificato con Pillow: se non è una vera immagine viene rifiutato;
- l'immagine viene ri-codificata in WebP: elimina metadati EXIF (posizione GPS) ed eventuali
  contenuti nascosti;
- il nome su disco è casuale; il nome originale non viene mai usato come percorso;
- i file sono salvati in instance/uploads (fuori da /static) e serviti da route con controllo permessi.
"""
from __future__ import annotations

import os
import uuid

from flask import current_app
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.datastructures import FileStorage

from app.services import ServiceError

ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif"}
Image.MAX_IMAGE_PIXELS = 40_000_000  # protezione da "decompression bomb"


def upload_dir(subdir: str) -> str:
    base = current_app.config["UPLOAD_FOLDER"]
    if not os.path.isabs(base):
        base = os.path.join(current_app.instance_path, base)
    path = os.path.join(base, subdir)
    os.makedirs(path, exist_ok=True)
    return path


def _extension(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def save_image(file: FileStorage, subdir: str, max_side: int) -> str:
    """Valida, ridimensiona e salva un'immagine. Restituisce il nome del file salvato."""
    if not file or not file.filename:
        raise ServiceError("Nessun file selezionato.")
    if _extension(file.filename) not in ALLOWED_IMAGE_EXTENSIONS:
        raise ServiceError("Formato non supportato. Usa JPG, PNG, WebP o GIF.")
    try:
        with Image.open(file.stream) as probe:
            probe.verify()
        file.stream.seek(0)
        with Image.open(file.stream) as img:
            img = ImageOps.exif_transpose(img)
            img = img.convert("RGBA") if img.mode in ("RGBA", "LA", "P") else img.convert("RGB")
            img.thumbnail((max_side, max_side))
            filename = f"{uuid.uuid4().hex}.webp"
            img.save(os.path.join(upload_dir(subdir), filename), "WEBP", quality=85)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ServiceError("Il file caricato non è un'immagine valida.") from exc
    return filename


def delete_upload(subdir: str, filename: str | None) -> None:
    if not filename:
        return
    safe_name = os.path.basename(filename)
    path = os.path.join(upload_dir(subdir), safe_name)
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
