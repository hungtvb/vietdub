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
import math
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
    if step == "review":
        return (set(data) == {"pending"}
                and (data["pending"] is None or
                     isinstance(data["pending"], str) and data["pending"] in {"asr", "translate"}))
    if step == "source_review":
        return (_valid_review_models("asr", data)
                and _valid_review_models("gender", data))
    if step in ("asr", "translate", "gender", "analyze"):
        return _valid_review_models(step, data)
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


def _valid_review_models(step: str, data: dict) -> bool:
    """Check the models and field types actually consumed by review widgets."""
    from project.schema import Segment, Speaker

    model = Segment if step in {"asr", "translate"} else Speaker
    rows = data.get("segments" if model is Segment else "speakers")
    if not isinstance(rows, list):
        return False
    try:
        for row in rows:
            value = model.from_dict(row)
            for name, item in vars(value).items():
                if name in {"index", "speaker", "id"}:
                    if type(item) is not int:
                        return False
                elif name in {"start", "end", "confidence", "median_hz"}:
                    if (isinstance(item, bool) or not isinstance(item, (int, float))
                            or not math.isfinite(item)):
                        return False
                elif name == "needs_review":
                    if type(item) is not bool:
                        return False
                elif name == "relations":
                    if not isinstance(item, list) or any(
                            not isinstance(rel, dict)
                            or any(not isinstance(rel.get(key, ""), str)
                                   for key in ("audience", "pronoun_i", "pronoun_you"))
                            for rel in item):
                        return False
                elif not isinstance(item, str):
                    return False
        meta = data.get("video_metadata", {})
        if step == "analyze" and not isinstance(meta, dict):
            return False
    except (TypeError, ValueError, AttributeError, KeyError, OverflowError):
        return False
    return True


def _nonempty_file(path: Any) -> bool:
    """Return whether an artifact exists as a non-empty regular file."""
    try:
        artifact = Path(path)
        return artifact.is_file() and artifact.stat().st_size > 0
    except (OSError, TypeError, ValueError):
        return False


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


def has_step(job_dir: Path, step: str, *, sub_mode: str = "") -> bool:
    """True only if the checkpoint and its produced artifacts are valid."""
    data = load_step(job_dir, step)
    if data is None:
        return False
    artifact_key = {"fetch": "video_path", "extract": "wav_path",
                    "mix": "mixed_wav", "render": "video_out"}.get(step)
    if artifact_key and not _nonempty_file(data[artifact_key]):
        return False
    if step == "tts":
        for segment in data["segments"]:
            if not isinstance(segment, dict):
                return False
            if segment.get("audio_vi") and not _nonempty_file(segment["audio_vi"]):
                return False
        meta = load_step(job_dir, "tts_meta")
        return bool(meta and _nonempty_file(meta.get("dub_track")))
    if step == "render" and sub_mode == "srt":
        srt_out = data.get("srt_out")
        if srt_out:
            return _nonempty_file(srt_out)
        try:
            return _nonempty_file(Path(data["video_out"]).with_suffix(".srt"))
        except (OSError, TypeError, ValueError):
            return False
    return True


def invalidate_from(job_dir: Path, project, step: str) -> None:
    """Discard a rerun step and every result that depends on it."""
    stale = STEPS[STEPS.index(step):]
    for name in stale:
        stage_path(job_dir, name).unlink(missing_ok=True)
    # Source review is an input to gender estimation, not a completed stage.
    # Keep it while retrying gender, but discard it when ASR or an earlier
    # stage is rebuilt because its speaker/segment IDs may no longer match.
    if STEPS.index(step) <= STEPS.index("asr"):
        stage_path(job_dir, "source_review").unlink(missing_ok=True)
    if "tts" in stale:
        stage_path(job_dir, "tts_meta").unlink(missing_ok=True)
    project.stages_done = [name for name in project.stages_done
                           if name not in stale]
