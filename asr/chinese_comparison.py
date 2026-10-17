"""Compare independent Chinese ASR hypotheses without claiming either is truth.

Normalize Simplified/Traditional script when OpenCC is available, because a
transcript in Traditional must not be marked wrong solely for its characters.
Timestamped windows are triage aids, NOT official CER/WER measurements.
"""
from __future__ import annotations

from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
import json
from typing import Iterable


@lru_cache(maxsize=1)
def _t2s_converter():
    try:
        from opencc import OpenCC
        return OpenCC("t2s")
    except ImportError:
        return None


def hanzi_only(value: str) -> str:
    return "".join(ch for ch in value if "\u3400" <= ch <= "\u9fff")


def normalize_hanzi(value: str) -> str | None:
    converter = _t2s_converter()
    if converter is None:
        return None
    return hanzi_only(converter.convert(hanzi_only(value)))


def extract_window(segments: Iterable[dict], start: float, end: float) -> str:
    """Assign an utterance to only one window by midpoint.

    This prevents the same original utterance being counted in multiple
    adjacent windows. Utterances crossing a window edge remain approximate.
    """
    if end <= start:
        raise ValueError("Invalid time window")
    ordered = sorted(segments, key=lambda s: float(s["start"]))
    return "".join(
        s.get("text_src") or s.get("text") or ""
        for s in ordered
        if start <= (float(s["start"]) + float(s["end"])) / 2 < end
    )


def _agreement(a: str, b: str) -> float | None:
    if not (a or b):
        return None
    return round(SequenceMatcher(None, a, b, autojunk=False).ratio(), 4)


def compare_transcripts(first: list[dict], second: list[dict],
                        *, duration: float = 30., window_seconds: float = 10.):
    if duration <= 0 or window_seconds <= 0:
        raise ValueError("Invalid comparison window")
    windows = []
    start = 0.
    script_normalized = _t2s_converter() is not None
    while start < duration:
        end = min(start + window_seconds, duration)
        raw_a = hanzi_only(extract_window(first, start, end))
        raw_b = hanzi_only(extract_window(second, start, end))
        norm_a = normalize_hanzi(raw_a) if script_normalized else None
        norm_b = normalize_hanzi(raw_b) if script_normalized else None
        windows.append({
            "start": round(start, 2), "end": round(end, 2),
            "funasr_hanzi": raw_a, "whisper_hanzi": raw_b,
            "funasr_simplified": norm_a, "whisper_simplified": norm_b,
            "raw_sequence_agreement": _agreement(raw_a, raw_b),
            "normalized_sequence_agreement": (
                _agreement(norm_a, norm_b) if script_normalized else None),
            "requires_editorial_review": (
                norm_a != norm_b if script_normalized else raw_a != raw_b),
            "window_is_approximate": True,
        })
        start = end

    all_a = "".join(item["funasr_hanzi"] for item in windows)
    all_b = "".join(item["whisper_hanzi"] for item in windows)
    normalized_a = normalize_hanzi(all_a) if script_normalized else None
    normalized_b = normalize_hanzi(all_b) if script_normalized else None
    normalized_agreement = (
        _agreement(normalized_a, normalized_b) if script_normalized else None)
    return {
        "metric": "cross_model_character_sequence_agreement_NOT_CER_OR_WER",
        "human_reference_verified": False,
        "script_normalization": (
            "opencc_t2s" if script_normalized else "unavailable_not_normalized"),
        "raw_character_sequence_agreement": _agreement(all_a, all_b),
        "normalized_character_sequence_agreement": normalized_agreement,
        "funasr_hanzi_count": len(all_a),
        "whisper_hanzi_count": len(all_b),
        "disagreement_windows": sum(x["requires_editorial_review"] for x in windows),
        "windows": windows,
        "limitations": [
            "Time windows use segment midpoints, not acoustically matched words.",
            "Neither hypothesis has been verified against a human reference.",
            "Chinese written variants are normalized only if OpenCC is installed.",
        ],
    }


def write_comparison(first, second, out, duration=30., window_seconds=10.):
    result = compare_transcripts(first, second, duration=duration,
                                 window_seconds=window_seconds)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
