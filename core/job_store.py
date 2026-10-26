"""Versioned metadata records for jobs; project/checkpoint data stays separate."""
from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.job import JOBS_ROOT, Job
from core.json_io import atomic_write_json
from core.checkpoint import STEPS

SCHEMA_VERSION = 1
STATUSES = {"idle", "running", "paused", "review", "done", "failed", "cancelled"}
JOB_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@dataclass
class JobRecord:
    schema_version: int
    job_id: str
    created_at: str
    updated_at: str
    status: str
    resume_from: str | None
    last_stage: str | None
    progress: float
    source_identity: dict[str, Any] | None
    last_error: str | None


class JobRecordError(ValueError):
    """A persisted job record is invalid or uses an unsupported version."""


class JobStore:
    def __init__(self, root: Path = JOBS_ROOT):
        self.root = Path(root)

    def _path(self, job_id: str) -> Path:
        if not isinstance(job_id, str) or not JOB_ID_RE.fullmatch(job_id):
            raise ValueError("invalid job_id")
        root = self.root.resolve()
        path = (root / job_id).resolve()
        if path.parent != root:
            raise ValueError("job_id must identify an immediate child of jobs root")
        return path / "job.json"

    def record_path(self, job_id: str) -> Path:
        return self._path(job_id)

    def save(self, job: Job, *, last_stage: str | None = None,
             progress: float | None = None, last_error: str | None = None,
             refresh_source_identity: bool = False) -> JobRecord:
        path = self._path(job.job_id)
        prior: JobRecord | None = None
        if not path.exists() and path.with_name(path.name + ".corrupt").exists():
            raise JobRecordError(f"quarantined job record exists for {job.job_id}")
        if path.exists():
            prior = self.load(job.job_id)  # invalid records are never overwritten
        now = _now()
        if last_stage is None and prior is not None:
            last_stage = prior.last_stage
        if progress is None:
            progress = prior.progress if prior is not None else 0.0
        if last_error is None and prior is not None:
            last_error = prior.last_error
        source = (self._source_identity(job) if prior is None or refresh_source_identity
                  else prior.source_identity)
        record = JobRecord(SCHEMA_VERSION, job.job_id,
                           prior.created_at if prior else now, now,
                           job.status, job.resume_from, last_stage, float(progress),
                           source, last_error)
        _validate(asdict(record), job_id=job.job_id)
        atomic_write_json(path, asdict(record))
        return record

    def load(self, job_id: str) -> JobRecord:
        path = self._path(job_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            _validate(payload, job_id=job_id)
            return JobRecord(**payload)
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError,
                KeyError, JobRecordError, ValueError) as exc:
            if path.exists():
                corrupt = path.with_name(path.name + ".corrupt")
                if not corrupt.exists():
                    try:
                        path.replace(corrupt)
                    except OSError:
                        pass
            if isinstance(exc, JobRecordError):
                raise
            raise JobRecordError(f"invalid job record for {job_id}: {exc}") from exc

    def _source_identity(self, job: Job) -> dict[str, Any] | None:
        project = job.project
        if project.video_source == "url" and project.video_url:
            local = Path(project.video_in).expanduser() if project.video_in else None
            job_local = (local is not None and local.exists() and
                         local.resolve().is_relative_to((self.root / job.job_id).resolve()))
            if not job_local:
                return {"kind": "url", "url": project.video_url}
            path = local
        else:
            if not project.video_in:
                return None
            path = Path(project.video_in).expanduser()
        try:
            stat = path.stat()
        except OSError:
            return {"kind": "file", "path": str(path), "size_bytes": None,
                    "mtime_ns": None}
        return {"kind": "file", "path": str(path), "size_bytes": stat.st_size,
                "mtime_ns": stat.st_mtime_ns}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _validate(value: Any, *, job_id: str) -> None:
    if not isinstance(value, dict):
        raise JobRecordError("record must be an object")
    fields = {"schema_version", "job_id", "created_at", "updated_at", "status",
              "resume_from", "last_stage", "progress", "source_identity", "last_error"}
    if set(value) != fields:
        raise JobRecordError("record fields do not match schema version 1")
    if value["schema_version"] != SCHEMA_VERSION:
        raise JobRecordError("unsupported schema version")
    if value["job_id"] != job_id or not JOB_ID_RE.fullmatch(job_id):
        raise JobRecordError("invalid job_id")
    for key in ("created_at", "updated_at"):
        try:
            parsed = datetime.fromisoformat(value[key].replace("Z", "+00:00"))
            if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
                raise ValueError("timestamp must be UTC")
        except (AttributeError, TypeError, ValueError) as exc:
            raise JobRecordError(f"invalid {key}") from exc
    if not isinstance(value["status"], str) or value["status"] not in STATUSES:
        raise JobRecordError("invalid persisted status")
    for key in ("resume_from", "last_stage"):
        if value[key] is not None and (not isinstance(value[key], str) or value[key] not in STEPS):
            raise JobRecordError(f"invalid {key}")
    progress = value["progress"]
    if isinstance(progress, bool) or not isinstance(progress, (int, float)) or not math.isfinite(progress) or not 0 <= progress <= 100:
        raise JobRecordError("progress must be finite and between 0 and 100")
    source = value["source_identity"]
    if source is not None:
        if not isinstance(source, dict) or source.get("kind") not in {"file", "url"}:
            raise JobRecordError("invalid source_identity")
        if source["kind"] == "url":
            if set(source) != {"kind", "url"} or not isinstance(source["url"], str):
                raise JobRecordError("invalid URL source identity")
        elif (set(source) != {"kind", "path", "size_bytes", "mtime_ns"}
              or not isinstance(source["path"], str)
              or (source["size_bytes"] is not None and (isinstance(source["size_bytes"], bool) or not isinstance(source["size_bytes"], int)))
              or (source["mtime_ns"] is not None and (isinstance(source["mtime_ns"], bool) or not isinstance(source["mtime_ns"], int)))):
            raise JobRecordError("invalid file source identity")
    if value["last_error"] is not None and not isinstance(value["last_error"], str):
        raise JobRecordError("invalid last_error")
