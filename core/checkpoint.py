# VietDub - Vietnamese dubbing for Chinese videos (PySide6 desktop app)
# Copyright (C) 2026 VietDub contributors
# License: GNU General Public License v3.0 (see LICENSE)
"""Real per-step checkpoints: jobs/<job_id>/stages/<step>.json.

Written after every pipeline step. On resume, a step whose checkpoint loads
valid is skipped. Corrupt checkpoint -> drop the broken file, re-run from
the previous step (edge case 16)."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("vietdub.checkpoint")

STEPS = ["fetch", "extract", "asr", "gender", "analyze", "translate",
         "tts", "mix", "render"]


def stage_path(job_dir: Path, step: str) -> Path:
    return Path(job_dir) / "stages" / f"{step}.json"


def save_step(job_dir: Path, step: str, data: Any) -> Path:
    """Atomically write a checkpoint (write tmp + rename)."""
    p = stage_path(job_dir, step)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)
    log.debug("checkpoint saved: %s", p)
    return p


def load_step(job_dir: Path, step: str) -> Optional[Any]:
    """Load a checkpoint. Returns None when missing OR corrupt.

    Corrupt files are renamed to <step>.json.corrupt (evidence kept) and
    treated as missing, so the caller re-runs from the previous step.
    """
    p = stage_path(job_dir, step)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
        log.warning("checkpoint corrupt, dropping %s: %s", p, e)
        try:
            p.rename(p.with_suffix(".json.corrupt"))
        except OSError:
            pass
        return None
    if not _looks_valid(step, data):
        log.warning("checkpoint %s failed structure check, dropping", p)
        try:
            p.rename(p.with_suffix(".json.corrupt"))
        except OSError:
            pass
        return None
    return data


def _looks_valid(step: str, data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    if step in ("asr", "translate", "gender", "analyze"):
        return isinstance(data.get("segments" if step != "gender" and step != "analyze" else
                                   ("speakers" if step in ("gender", "analyze") else None)), list)
    if step == "fetch":
        return bool(data.get("video_path"))
    if step == "extract":
        return bool(data.get("wav_path"))
    if step == "tts":
        return isinstance(data.get("segments"), list)
    if step == "mix":
        return bool(data.get("mixed_wav"))
    if step == "render":
        return bool(data.get("video_out"))
    return True


def mark_done(job_dir: Path, project, step: str) -> None:
    """Record a finished step.

    project may be a Project dataclass (preferred: its in-RAM
    stages_done is updated too) or a plain dict (legacy callers/tests).
    """
    if hasattr(project, "stages_done"):  # Project dataclass
        if step not in project.stages_done:
            project.stages_done.append(step)
        project_dict = project.to_dict()
    else:  # plain dict
        project_dict = project
        done = project_dict.setdefault("stages_done", [])
        if step not in done:
            done.append(step)
    (Path(job_dir) / "project.json").write_text(
        json.dumps(project_dict, ensure_ascii=False, indent=1), encoding="utf-8")


def has_step(job_dir: Path, step: str) -> bool:
    """True only if the checkpoint exists AND loads valid."""
    return load_step(job_dir, step) is not None
