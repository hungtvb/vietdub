"""Compare two *real* Mandarin ASR transcripts without pretending either is truth.

No reference WER/CER is reported until a human-reviewed transcript exists.
Suitable for any Chinese recording, not coupled to the regression interview.
"""
from __future__ import annotations

from difflib import SequenceMatcher
from pathlib import Path
import json
import re
from typing import Iterable


def hanzi_only(value: str) -> str:
    return "".join(ch for ch in value if "\u3400" <= ch <= "\u9fff")


def extract_window(segments: Iterable[dict], start: float, end: float) -> str:
    if end <= start:
        raise ValueError("Invalid time window")
    ordered = sorted(segments, key=lambda s: float(s["start"]))
    return "".join(
        s.get("text_src") or s.get("text") or ""
        for s in ordered if float(s["start"]) < end and
        float(s["end"]) > start
    )


def compare_transcripts(first: list[dict], second: list[dict],
                        *, duration: float = 30., window_seconds: float = 10.):
    if duration <= 0 or window_seconds <= 0:
        raise ValueError("Invalid comparison window")
    windows = []
    start = 0.
    while start < duration:
        end = min(start + window_seconds, duration)
        a = hanzi_only(extract_window(first, start, end))
        b = hanzi_only(extract_window(second, start, end))
        ratio = (SequenceMatcher(None, a, b, autojunk=False).ratio()
                 if a or b else None)
        windows.append({
            "start": round(start, 2), "end": round(end, 2),
            "funasr_hanzi": a, "whisper_hanzi": b,
            "same_text": a == b,
            "sequence_agreement": round(ratio, 4) if ratio is not None else None,
            "requires_editorial_review": bool(a != b),
        })
        start = end
    all_a = "".join(item["funasr_hanzi"] for item in windows)
    all_b = "".join(item["whisper_hanzi"] for item in windows)
    aggregate = (SequenceMatcher(None, all_a, all_b, autojunk=False).ratio()
                 if all_a or all_b else None)
    return {
        "metric": "cross_model_character_sequence_agreement_NOT_CER_OR_WER",
        "human_reference_verified": False,
        "funasr_hanzi_count": len(all_a),
        "whisper_hanzi_count": len(all_b),
        "cross_model_agreement": round(aggregate, 4) if aggregate is not None else None,
        "disagreement_windows": sum(x["requires_editorial_review"] for x in windows),
        "windows": windows,
    }


def write_comparison(first, second, out, duration=30., window_seconds=10.):
    result = compare_transcripts(first, second, duration=duration,
                                 window_seconds=window_seconds)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
