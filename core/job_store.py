"""Versioned metadata records for jobs; project/checkpoint data stays separate."""
from __future__ import annotations

import json
import math
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.job import JOBS_ROOT, Job
from core.json_io import atomic_write_json, quarantine_file
from core.checkpoint import STEPS, has_step, load_step

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
             refresh_source_identity: bool = False,
             seed_fetched_identity: bool = False) -> JobRecord:
        path = self._path(job.job_id)
        prior: JobRecord | None = None
        if not path.exists() and os.path.lexists(path.with_name(path.name + ".corrupt")):
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
        seed = (seed_fetched_identity and job.project.video_source == "url"
                and (prior is None or (prior.source_identity is not None
                     and prior.source_identity.get("kind") == "url"
                     and prior.source_identity.get("url") == job.project.video_url)))
        source = (self._source_identity(job, refresh_download=refresh_source_identity or seed)
                  if prior is None or refresh_source_identity or seed
                  else prior.source_identity)
        record = JobRecord(SCHEMA_VERSION, job.job_id,
                           prior.created_at if prior else now, now,
                           job.status, job.resume_from, last_stage, progress,
                           source, last_error)
        _validate(asdict(record), job_id=job.job_id)
        atomic_write_json(path, asdict(record))
        return record

    def load(self, job_id: str) -> JobRecord:
        path = self._path(job_id)
        # Keep I/O failures distinct from malformed content. A transient
        # permission or filesystem error must never trigger quarantine.
        raw = path.read_bytes()
        try:
            payload = json.loads(raw.decode("utf-8"))
            _validate(payload, job_id=job_id)
            return JobRecord(**payload)
        except (UnicodeError, json.JSONDecodeError, TypeError,
                KeyError, JobRecordError, ValueError, OverflowError) as exc:
            reason = str(exc)
            corrupt = path.with_name(path.name + ".corrupt")
            try:
                quarantine_file(path)
            except OSError as quarantine_error:
                raise JobRecordError(
                    f"invalid job record for {job_id}: {reason}; "
                    f"could not preserve at {corrupt}: {quarantine_error}"
                ) from exc
            raise JobRecordError(
                f"invalid job record for {job_id}: {reason}; preserved at {corrupt}"
            ) from exc

    def _source_identity(self, job: Job, *, refresh_download: bool = False) -> dict[str, Any] | None:
        project = job.project
        if project.video_source == "url" and project.video_url:
            if not refresh_download:
                return {"kind": "url", "url": project.video_url}
            job_dir = self.root / job.job_id
            fetch = load_step(job_dir, "fetch") if has_step(job_dir, "fetch") else None
            local = (Path(fetch["video_path"]).expanduser() if fetch
                     else Path(project.video_in).expanduser() if project.video_in else None)
            job_local = (local is not None and local.exists() and
                         local.resolve().is_relative_to((self.root / job.job_id).resolve()))
            if not job_local:
                return {"kind": "url", "url": project.video_url}
            path = local
        else:
            if not project.video_in:
                return None
            path = Path(project.video_in).expanduser()
            # Explicit resume may be the first save of a legacy job whose
            # original was moved. Use the same validated input as execution.
            job_dir = self.root / job.job_id
            if not path.exists() and has_step(job_dir, "fetch"):
                path = Path(load_step(job_dir, "fetch")["video_path"])
        path = path.expanduser().resolve()
        stat = path.stat()
        return {"kind": "file", "path": os.path.normcase(str(path)),
                "size_bytes": stat.st_size,
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
    if type(value["schema_version"]) is not int or value["schema_version"] != SCHEMA_VERSION:
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
    # Check the range before float conversion: math.isfinite(huge_int) raises.
    if (isinstance(progress, bool) or not isinstance(progress, (int, float))
            or not 0 <= progress <= 100 or not math.isfinite(progress)):
        raise JobRecordError("progress must be finite and between 0 and 100")
    source = value["source_identity"]
    if source is not None:
        if (not isinstance(source, dict) or not isinstance(source.get("kind"), str)
                or source["kind"] not in {"file", "url"}):
            raise JobRecordError("invalid source_identity")
        if source["kind"] == "url":
            if set(source) != {"kind", "url"} or not isinstance(source["url"], str):
                raise JobRecordError("invalid URL source identity")
        elif (set(source) != {"kind", "path", "size_bytes", "mtime_ns"}
              or not isinstance(source["path"], str)
              or type(source["size_bytes"]) is not int
              or type(source["mtime_ns"]) is not int):
            raise JobRecordError("invalid file source identity")
    if value["last_error"] is not None and not isinstance(value["last_error"], str):
        raise JobRecordError("invalid last_error")
