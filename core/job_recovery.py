"""Read job history and calculate safe, non-executing recovery decisions."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from core import checkpoint
from core.job_store import JOB_ID_RE, JobRecord, JobRecordError, JobStore
from project.io import load_project
from project.schema import Project


@dataclass
class JobInspection:
    job_id: str
    project: Project | None = None
    source_label: str = ""
    display_status: str = "damaged"
    last_stage: str | None = None
    updated_at: str | None = None
    output_path: Path | None = None
    run_log_path: Path | None = None
    resume_from: str | None = None
    rebuild_steps: list[str] = field(default_factory=list)
    source_changed: bool = False
    blocked_reason: str | None = None
    legacy: bool = False
    damaged: bool = False


def discover_jobs(store: JobStore, *, sub_mode: str | None = None) -> list[JobInspection]:
    """Inspect immediate directory children independently; no pipeline work runs."""
    try:
        children = list(store.root.iterdir())
    except OSError:
        return []
    result = []
    for child in children:
        if child.is_symlink() or not child.is_dir():
            continue
        result.append(inspect_job(store, child.name, sub_mode=sub_mode))
    return sorted(result, key=lambda item: item.updated_at or "", reverse=True)


def inspect_job(store: JobStore, job_id: str, *, sub_mode: str | None = None) -> JobInspection:
    """Validate a saved job without resuming it or changing its project/record."""
    result = JobInspection(job_id=job_id, damaged=True, blocked_reason="Invalid job directory")
    if not JOB_ID_RE.fullmatch(job_id):
        return result
    job_dir = store.root / job_id
    if job_dir.is_symlink() or not job_dir.is_dir():
        return result
    try:
        if job_dir.resolve().parent != store.root.resolve():
            return result
    except OSError:
        return result
    result.run_log_path = job_dir / "run.log"
    project_path = job_dir / "project.json"
    try:
        project = load_project(job_dir)
        if (not isinstance(project, Project)
                or not all(isinstance(value, str) for value in
                           (project.name, project.video_source, project.video_in,
                            project.video_url, project.video_out, project.sub_mode))
                or project.video_source not in {"file", "url"}
                or not isinstance(project.stages_done, list)
                or any(not isinstance(step, str) or step not in checkpoint.STEPS
                       for step in project.stages_done)):
            raise ValueError("invalid project fields")
    except (OSError, ValueError, TypeError, AttributeError, KeyError, UnicodeError) as exc:
        result.blocked_reason = f"Invalid project: {exc}"
        return result
    result.project = project
    result.source_label = project.video_url if project.video_source == "url" else project.video_in
    result.output_path = Path(project.video_out) if project.video_out else None
    record_path = job_dir / "job.json"
    record: JobRecord | None = None
    if record_path.exists():
        try:
            record = store.load(job_id)
        except (JobRecordError, OSError, ValueError) as exc:
            result.blocked_reason = f"Invalid job metadata: {exc}"
            return result
        result.updated_at = record.updated_at
        result.last_stage = record.last_stage
        result.display_status = "interrupted" if record.status == "running" else record.status
    elif (job_dir / "job.json.corrupt").exists():
        result.blocked_reason = "Quarantined job metadata"
        return result
    else:
        result.legacy = True
        try:
            result.updated_at = datetime.fromtimestamp(
                project_path.stat().st_mtime, timezone.utc
            ).isoformat().replace("+00:00", "Z")
        except OSError as exc:
            result.blocked_reason = f"Cannot read project timestamp: {exc}"
            return result

    result.damaged = False
    result.blocked_reason = None
    mode = sub_mode or project.sub_mode or "burn"
    valid = []
    for step in checkpoint.STEPS:
        if not checkpoint.has_step(job_dir, step, sub_mode=mode):
            break
        valid.append(step)
    if valid:
        result.last_stage = result.last_stage or valid[-1]
    if len(valid) < len(checkpoint.STEPS):
        result.resume_from = checkpoint.STEPS[len(valid)]
        result.rebuild_steps = checkpoint.STEPS[len(valid):].copy()
    if result.legacy:
        if len(valid) == len(checkpoint.STEPS):
            result.display_status = "done"
        elif valid and valid[-1] in {"asr", "translate"} and project.effective_review_stops():
            result.display_status = "review"
        elif valid:
            result.display_status = "interrupted"
        else:
            result.display_status = "idle"

    if record and record.source_identity and record.source_identity["kind"] == "file":
        source = record.source_identity
        path = Path(source["path"])
        if path.exists():
            try:
                stat = path.stat()
                current = os.path.normcase(str(path.resolve()))
                project_path_value = (os.path.normcase(str(Path(project.video_in).expanduser().resolve()))
                                      if project.video_in else current)
                if (current != source["path"] or project_path_value != current
                        or stat.st_size != source["size_bytes"]
                        or stat.st_mtime_ns != source["mtime_ns"]):
                    result.source_changed = True
            except OSError:
                result.blocked_reason = "Cannot inspect recorded source"
        elif project.video_in:
            alternate = Path(project.video_in).expanduser()
            if alternate.exists() and alternate.resolve() != path.resolve():
                result.source_changed = True
    elif record and record.source_identity and record.source_identity["kind"] == "url":
        if project.video_url != record.source_identity["url"]:
            result.source_changed = True
    if result.source_changed:
        result.resume_from = "fetch"
        result.rebuild_steps = checkpoint.STEPS.copy()
        return result

    # A valid fetch checkpoint is the canonical input for later stages.
    if result.resume_from == "fetch":
        local = Path(project.video_in).expanduser() if project.video_in else None
        if not (project.video_source == "url" and project.video_url) \
                and (not local or not _readable_file(local)):
            result.blocked_reason = "Source video is missing or unreadable"
    return result


def _readable_file(path: Path) -> bool:
    try:
        with path.open("rb") as source:
            source.read(1)
        return path.is_file()
    except (OSError, ValueError):
        return False
