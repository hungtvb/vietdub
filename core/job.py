# VietDub - Vietnamese dubbing for Chinese videos (PySide6 desktop app)
# Copyright (C) 2026 VietDub contributors
# License: GNU General Public License v3.0 (see LICENSE)
"""Job = 1 video + config + state. Independent from the start so a future
BatchQueue can run many jobs sequentially without touching the core."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from project.schema import Project

# Job states
IDLE = "idle"
RUNNING = "running"
PAUSED = "paused"
REVIEW = "review"   # waiting at a review stop (only when not overnight)
DONE = "done"
FAILED = "failed"
CANCELLED = "cancelled"  # user cancelled mid-run (Wave 2 UI)

JOBS_ROOT = Path(__file__).resolve().parents[1] / "jobs"


@dataclass
class Job:
    """One dubbing job: one video + its config + its state.

    The orchestrator takes exactly one Job and knows nothing about queues.
    Each job owns its directory jobs/<job_id>/ (checkpoints, logs, tts wavs),
    so one job crashing never affects another.
    """
    job_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    project: Project = field(default_factory=Project)
    status: str = IDLE
    # resume support: step name to continue from (None = from the start)
    resume_from: Optional[str] = None
    # optional callbacks (UI wires these in Wave 2; core never blocks on them)
    progress_cb: Optional[Callable[[str, float, str], None]] = None
    log_cb: Optional[Callable[[str], None]] = None
    # UI control flags (Wave 2): checked by the orchestrator between steps.
    # Transient - never saved to disk (a restarted app resumes from checkpoint).
    pause_requested: bool = False
    cancel_requested: bool = False

    @property
    def job_dir(self) -> Path:
        d = JOBS_ROOT / self.job_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def stages_dir(self) -> Path:
        d = self.job_dir / "stages"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def run_log_path(self) -> Path:
        return self.job_dir / "run.log"

    def emit_progress(self, step: str, pct: float, msg: str = "") -> None:
        if self.progress_cb:
            try:
                self.progress_cb(step, pct, msg)
            except Exception:
                pass

    def emit_log(self, line: str) -> None:
        if self.log_cb:
            try:
                self.log_cb(line)
            except Exception:
                pass

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "project": self.project.to_dict(),
            "status": self.status,
            "resume_from": self.resume_from,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Job":
        return cls(
            job_id=d.get("job_id", uuid.uuid4().hex[:12]),
            project=Project.from_dict(d.get("project", {})),
            status=d.get("status", IDLE),
            resume_from=d.get("resume_from"),
        )
