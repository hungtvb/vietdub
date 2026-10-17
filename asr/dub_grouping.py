"""Deterministic source-ID-preserving Chinese utterance grouping for dubbing.

FunASR may split speech into sub-second utterances or single Hanzi. Translating
and calling TTS on these fragments independently is often impossible in a
Vietnamese timeline. Regrouping never claims corrected ASR content, speaker
identity, or approved translation; source IDs remain auditable.
"""
from __future__ import annotations

from project.schema import Segment

FINAL_PUNC = frozenset("。！？!?")
MAX_GAP_SECONDS = 1.0
MAX_WINDOW_SECONDS = 12.0
TARGET_WINDOW_SECONDS = 9.0
MIN_SENTENCE_WINDOW_SECONDS = 5.0


def group_for_vietnamese_dub(source: list[Segment]):
    """Return (dub_units, per-unit source index mapping).

    Only contiguous same-speaker source units can be joined.
    No source utterance is removed or reassigned to another speaker.
    """
    if not source:
        raise ValueError("Empty Chinese source transcript")
    output: list[Segment] = []
    mapping: list[dict] = []
    selected: list[Segment] = []

    def flush():
        if not selected:
            return
        ids = [seg.index for seg in selected]
        unit = Segment(
            index=len(output),
            start=selected[0].start,
            end=selected[-1].end,
            speaker=selected[0].speaker,
            text_src="".join(seg.text_src.strip() for seg in selected),
            source_lang="zh",
            needs_review=True,
        )
        output.append(unit)
        mapping.append({"dub_index": unit.index, "original_asr_ids": ids,
                        "start": unit.start, "end": unit.end,
                        "source_speaker_hypothesis": unit.speaker,
                        "human_verified": False})
        selected.clear()

    for seg in source:
        if selected:
            gap = seg.start - selected[-1].end
            window = seg.end - selected[0].start
            if (seg.speaker != selected[-1].speaker
                    or gap > MAX_GAP_SECONDS
                    or window > MAX_WINDOW_SECONDS):
                flush()
        selected.append(seg)
        duration = selected[-1].end - selected[0].start
        if (duration >= TARGET_WINDOW_SECONDS or
                (duration >= MIN_SENTENCE_WINDOW_SECONDS and
                 any(seg.text_src.rstrip().endswith(p) for p in FINAL_PUNC))):
            flush()
    flush()
    recovered = [source_id for item in mapping
                 for source_id in item["original_asr_ids"]]
    expected = [seg.index for seg in source]
    if recovered != expected:
        raise RuntimeError("Dubbing grouping lost, duplicated or reordered ASR evidence")
    if any(unit.end <= unit.start for unit in output):
        raise RuntimeError("Invalid merged utterance timing")
    return output, mapping
