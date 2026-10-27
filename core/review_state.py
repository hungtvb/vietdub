"""Durable review intent, independent of stage completion and UI navigation."""
from __future__ import annotations

from core import checkpoint
from core.json_io import atomic_write_json

REVIEW_NEXT = {"asr": "gender", "translate": "tts"}


def save_pending_review(job_dir, step: str | None) -> None:
    if step is not None and step not in REVIEW_NEXT:
        raise ValueError("invalid review stage")
    # Write before producing a review checkpoint; clear only on explicit
    # approval. A crash or failed job.json save cannot approve that checkpoint.
    atomic_write_json(checkpoint.stage_path(job_dir, "review"), {"pending": step})


def pending_review(job_dir, project, record, valid_steps: list[str]) -> str | None:
    if not project.effective_review_stops():
        return None
    if record and record.status == "done":
        return None
    state = checkpoint.load_step(job_dir, "review")
    if state is not None:
        return state["pending"]
    # Compatibility with records written before durable review intent existed.
    # A gender checkpoint can contain edits saved by Back, not approval, so a
    # saved REVIEW state is authoritative. A RUNNING/FAILED record at a review
    # boundary is only inferred as pending when its resume point has not
    # already advanced beyond that boundary (which means the user approved it).
    if record:
        if record.status == "review" and record.last_stage in REVIEW_NEXT:
            return record.last_stage
        if (record.status in {"running", "failed"}
                and record.last_stage in REVIEW_NEXT
                and record.resume_from != REVIEW_NEXT[record.last_stage]):
            return record.last_stage
        return None

    # Legacy projects lack explicit lifecycle state, so their last valid
    # checkpoint remains the safest available signal. A Back action may save
    # gender data without marking the gender pipeline stage complete.
    if valid_steps and valid_steps[-1] in {"asr", "gender", "translate"}:
        return "translate" if valid_steps[-1] == "translate" else "asr"
    return None
