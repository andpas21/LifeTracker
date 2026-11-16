"""Backup del server: database SQLite (copia consistente) + file caricati, in un archivio .zip.

I backup contengono i dati di tutte le famiglie del server: sono gestiti solo dall'amministratore
del sistema (riga di comando / timer systemd), non dall'interfaccia web.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
import zipfile
from datetime import datetime

from flask import current_app

from app.extensions import db


def backup_dir() -> str:
    path = current_app.config.get("BACKUP_FOLDER") or "backups"
    if not os.path.isabs(path):
        path = os.path.join(current_app.instance_path, path)
    os.makedirs(path, exist_ok=True)
    return path


def _sqlite_path() -> str | None:
    url = db.engine.url
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        return None
    return url.database


def create_backup() -> str:
    """Crea un archivio zip e applica la rotazione. Restituisce il percorso del file creato."""
    db_path = _sqlite_path()
    if db_path is None:
        raise RuntimeError("Backup automatico disponibile solo con SQLite: per PostgreSQL usa pg_dump.")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = os.path.join(backup_dir(), f"lifetracker-{stamp}.zip")
    n = 1
    while os.path.exists(target):  # due backup nello stesso secondo
        target = os.path.join(backup_dir(), f"lifetracker-{stamp}-{n}.zip")
        n += 1
    with tempfile.TemporaryDirectory() as tmp:
        copy = os.path.join(tmp, "lifetracker.db")
        source = sqlite3.connect(db_path)
        dest = sqlite3.connect(copy)
        with dest:
            source.backup(dest)  # copia coerente anche con l'app in esecuzione
        source.close()
        dest.close()
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(copy, "lifetracker.db")
            uploads = current_app.config["UPLOAD_FOLDER"]
            if not os.path.isabs(uploads):
                uploads = os.path.join(current_app.instance_path, uploads)
            if os.path.isdir(uploads):
                for root, _, files in os.walk(uploads):
                    for name in files:
                        full = os.path.join(root, name)
                        archive.write(full, os.path.join("uploads", os.path.relpath(full, uploads)))
    rotate()
    current_app.logger.info("Backup creato: %s", target)
    return target


def list_backups() -> list[str]:
    folder = backup_dir()
    files = [os.path.join(folder, f) for f in os.listdir(folder)
             if f.startswith("lifetracker-") and f.endswith(".zip")]
    return sorted(files, key=os.path.getmtime, reverse=True)


def rotate() -> None:
    keep = int(current_app.config.get("BACKUP_KEEP", 14))
    for old in list_backups()[keep:]:
        os.remove(old)


def backup_due(max_age_hours: int = 24) -> bool:
    backups = list_backups()
    if not backups:
        return True
    age = datetime.now().timestamp() - os.path.getmtime(backups[0])
    return age >= max_age_hours * 3600


def restore_backup(archive_path: str) -> None:
    """Ripristina database e upload da un archivio (l'app deve essere ferma)."""
    db_path = _sqlite_path()
    if db_path is None:
        raise RuntimeError("Ripristino disponibile solo con SQLite.")
    uploads = current_app.config["UPLOAD_FOLDER"]
    if not os.path.isabs(uploads):
        uploads = os.path.join(current_app.instance_path, uploads)
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        if "lifetracker.db" not in names or any(n.startswith("/") or ".." in n for n in names):
            raise RuntimeError("Archivio non valido.")
        db.session.remove()
        db.engine.dispose()
        with archive.open("lifetracker.db") as src, open(db_path, "wb") as dst:
            dst.write(src.read())
        for suffix in ("-wal", "-shm"):
            if os.path.exists(db_path + suffix):
                os.remove(db_path + suffix)
        for name in names:
            if name.startswith("uploads/") and not name.endswith("/"):
                target = os.path.join(uploads, os.path.relpath(name, "uploads"))
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with archive.open(name) as src, open(target, "wb") as dst:
                    dst.write(src.read())
