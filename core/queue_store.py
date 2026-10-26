"""Versioned storage for the single ordered active batch queue."""
from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from core.json_io import atomic_write_json, quarantine_file
from core.paths import user_data_dir

ACTIVE_QUEUE_PATH = user_data_dir() / "active_queue.json"
SCHEMA_VERSION = 1
STATES = {"queued", "done", "skipped"}
ENTRY_ID_RE = re.compile(r"^[0-9a-f]{32}$")
JOB_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _canonical_path(path: str | Path) -> str:
    return os.path.normcase(str(Path(path).expanduser().resolve()))


@dataclass
class QueueItemRecord:
    path: str
    state: str = "queued"
    job_id: str | None = None
    entry_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def __post_init__(self) -> None:
        # New entries have a canonical path. Persisted paths are checked
        # against their original bytes before constructing this record.
        if isinstance(self.path, (str, Path)):
            self.path = _canonical_path(self.path)


@dataclass
class QueueManifest:
    schema_version: int = SCHEMA_VERSION
    entries: list[QueueItemRecord] = field(default_factory=list)
    active_entry_id: str | None = None


class QueueStoreError(ValueError):
    """A queue manifest is malformed or uses an unsupported version."""


def _validate(payload: Any) -> None:
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version", "entries", "active_entry_id"
    }:
        raise QueueStoreError("manifest fields do not match schema version 1")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != SCHEMA_VERSION:
        raise QueueStoreError("unsupported schema version")
    if not isinstance(payload["entries"], list):
        raise QueueStoreError("entries must be an array")
    ids: set[str] = set()
    paths: set[str] = set()
    for index, entry in enumerate(payload["entries"]):
        if not isinstance(entry, dict) or set(entry) != {
            "entry_id", "path", "state", "job_id"
        }:
            raise QueueStoreError(f"invalid entry fields at index {index}")
        entry_id = entry["entry_id"]
        if not isinstance(entry_id, str) or not ENTRY_ID_RE.fullmatch(entry_id):
            raise QueueStoreError(f"invalid entry_id at index {index}")
        if entry_id in ids:
            raise QueueStoreError("duplicate entry_id")
        ids.add(entry_id)
        path = entry["path"]
        if not isinstance(path, str) or not path or "\0" in path:
            raise QueueStoreError(f"invalid path at index {index}")
        try:
            canonical = _canonical_path(path)
        except (OSError, RuntimeError, ValueError) as exc:
            raise QueueStoreError(f"invalid path at index {index}: {exc}") from exc
        if not Path(path).is_absolute() or canonical != path:
            raise QueueStoreError(f"noncanonical path at index {index}")
        if canonical in paths:
            raise QueueStoreError("duplicate path")
        paths.add(canonical)
        if not isinstance(entry["state"], str) or entry["state"] not in STATES:
            raise QueueStoreError(f"invalid state at index {index}")
        job_id = entry["job_id"]
        if job_id is not None and (
            not isinstance(job_id, str) or not JOB_ID_RE.fullmatch(job_id)
        ):
            raise QueueStoreError(f"invalid job_id at index {index}")
    active = payload["active_entry_id"]
    if active is not None and (not isinstance(active, str) or active not in ids):
        raise QueueStoreError("active_entry_id is not in entries")


class QueueStore:
    def __init__(self, path: Path = ACTIVE_QUEUE_PATH):
        self.path = Path(path)

    def load(self) -> QueueManifest | None:
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            if os.path.lexists(self.path):
                raise
            return None
        try:
            payload = json.loads(raw.decode("utf-8"))
            _validate(payload)
            return QueueManifest(
                schema_version=payload["schema_version"],
                entries=[QueueItemRecord(**entry) for entry in payload["entries"]],
                active_entry_id=payload["active_entry_id"],
            )
        except (UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            corrupt = self.path.with_name(self.path.name + ".corrupt")
            try:
                quarantine_file(self.path)
            except OSError as quarantine_error:
                raise QueueStoreError(
                    f"invalid queue manifest at {self.path}: {exc}; "
                    f"could not preserve at {corrupt}: {quarantine_error}"
                ) from exc
            raise QueueStoreError(
                f"invalid queue manifest at {self.path}: {exc}; preserved at {corrupt}"
            ) from exc

    def save(self, manifest: QueueManifest) -> None:
        if not isinstance(manifest, QueueManifest):
            raise QueueStoreError("expected QueueManifest")
        if not isinstance(manifest.entries, list) or not all(
            isinstance(entry, QueueItemRecord) for entry in manifest.entries
        ):
            raise QueueStoreError("entries must be QueueItemRecord values")
        payload = asdict(manifest)
        _validate(payload)
        if os.path.lexists(self.path):
            self.load()  # never replace an invalid manifest
        elif os.path.lexists(self.path.with_name(self.path.name + ".corrupt")):
            raise QueueStoreError("quarantined queue manifest exists")
        atomic_write_json(self.path, payload)

    def clear(self) -> None:
        """Remove only the active manifest; leave job records and artifacts alone."""
        self.path.unlink(missing_ok=True)
