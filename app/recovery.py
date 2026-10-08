"""Single-owner data directory and conservative upload crash reconciliation."""
import hashlib
import json
import os
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import Document


def acquire_data_lock(directory):
    handle = (directory / ".writer.lock").open("a+b")
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            if handle.read(1) == b"":
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise RuntimeError("DATA_DIR is already owned by another Web worker")
    return handle


def reconcile_uploads(engine, directory):
    from .files import sync_directory
    summary = {"committedIntentsCleared": 0, "quarantined": [], "retainedAnomalies": []}
    with Session(engine) as session:
        records = {row.storage_key: (row.id, row.size_bytes, row.sha256) for row in session.scalars(select(Document))}
    quarantine = directory / "quarantine"

    def isolate(path, reason):
        # Only move actual workspace children, never follow a symlink outside DATA_DIR.
        if path.is_symlink() or path.resolve().parent not in {(directory / "tmp").resolve(), (directory / "uploads").resolve()}:
            summary["retainedAnomalies"].append(path.name)
            return
        destination = quarantine / (uuid.uuid4().hex + "-" + path.name)
        os.replace(path, destination)
        sync_directory(path.parent)
        sync_directory(quarantine)
        summary["quarantined"].append({"file": destination.name, "reason": reason})

    for path in (directory / "tmp").glob("*.intent.json"):
        try:
            intent = json.loads(path.read_text("utf-8"))
            key = intent["storageKey"]
            record = records.get(key)
            if record and record == (intent["documentId"], intent["sizeBytes"], intent["sha256"]):
                source = directory / "uploads" / key
                if source.is_symlink() or source.resolve().parent != (directory / "uploads").resolve():
                    raise ValueError("Invalid upload path")
                raw = source.read_bytes()
                if len(raw) != record[1] or hashlib.sha256(raw).hexdigest() != record[2]:
                    raise ValueError("Committed original differs from intent")
                path.unlink()
                sync_directory(path.parent)
                summary["committedIntentsCleared"] += 1
            elif record:
                summary["retainedAnomalies"].append(path.name)
            else:
                isolate(path, "metadata not committed; preserve intent for inspection")
        except (OSError, ValueError, KeyError, TypeError):
            summary["retainedAnomalies"].append(path.name)
    for path in (directory / "uploads").iterdir():
        if path.is_file() and path.name not in records:
            isolate(path, "formal file has no committed metadata; do not import or delete")
    for path in (directory / "tmp").glob("*.part"):
        isolate(path, "interrupted temporary upload")
    return summary
