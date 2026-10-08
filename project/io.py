# VietDub - Vietnamese dubbing for Chinese videos (PySide6 desktop app)
# Copyright (C) 2026 VietDub contributors
# License: GNU General Public License v3.0 (see LICENSE)
"""Project persistence: jobs/<job_id>/project.json + stages/*.json."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List

from project.schema import Project, Segment, Speaker

log = logging.getLogger("vietdub.project")


def save_project(job_dir: str | Path, project: Project) -> Path:
    p = Path(job_dir) / "project.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(project.to_dict(), ensure_ascii=False, indent=1),
                   encoding="utf-8")
    tmp.replace(p)
    return p


def load_project(job_dir: str | Path) -> Project:
    p = Path(job_dir) / "project.json"
    if not p.exists():
        raise FileNotFoundError(f"Không tìm thấy project: {p}")
    try:
        return Project.from_dict(json.loads(p.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError) as e:
        raise ValueError(
            f"File project bị hỏng: {p}\nCách khắc phục: tạo job mới.") from e


def save_segments(job_dir: str | Path, step: str,
                  segments: List[Segment]) -> Path:
    from core import checkpoint as cp
    return cp.save_step(job_dir, step,
                        {"segments": [s.to_dict() for s in segments]})


def load_segments(job_dir: str | Path, step: str) -> List[Segment] | None:
    from core import checkpoint as cp
    data = cp.load_step(job_dir, step)
    if data is None:
        return None
    return [Segment.from_dict(d) for d in data.get("segments", [])]


def save_speakers(job_dir: str | Path, step: str,
                  speakers: dict[int, Speaker]) -> Path:
    from core import checkpoint as cp
    return cp.save_step(job_dir, step,
                        {"speakers": [s.to_dict() for s in speakers.values()]})


def load_speakers(job_dir: str | Path, step: str) -> dict[int, Speaker] | None:
    from core import checkpoint as cp
    data = cp.load_step(job_dir, step)
    if data is None:
        return None
    return {s["id"]: Speaker.from_dict(s) for s in data.get("speakers", [])}
