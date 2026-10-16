# VietDub - local multilingual ASR + independent speaker diarization.
"""Production Whisper/pyannote adapter for the desktop app.

Never invents confidence or silently approves failed acoustic alignment.
HF_TOKEN is read from environment first; the user can set a token in app settings.
"""
from __future__ import annotations
from collections import defaultdict
from pathlib import Path
import json
import logging
import os

from project.schema import Segment
from asr.whisper_align import forced_align

log = logging.getLogger("vietdub.asr.hybrid")


def overlap(a, b, x, y):
    return max(0.0, min(b, y) - max(a, x))


def annotation_windows(annotation):
    if hasattr(annotation, "itertracks"):
        pairs = ((seg, label) for seg, _, label in annotation.itertracks(yield_label=True))
    else:
        pairs = annotation
    result = [{"start": float(seg.start), "end": float(seg.end), "label": str(label)}
              for seg, label in pairs]
    return sorted(result, key=lambda x: (x["start"], x["end"]))


def assign_speaker(start, end, windows):
    """Determine speaker acoustically from independent pyannote time windows."""
    votes = defaultdict(float)
    for win in windows:
        if win["start"] >= end:
            break
        duration = overlap(start, end, win["start"], win["end"])
        if duration:
            votes[win["label"]] += duration
    if not votes:
        return None, 0.0, 0.0
    ranked = sorted(votes.items(), key=lambda x: -x[1])
    label, value = ranked[0]
    return label, value / max(end - start, .001), value / max(sum(votes.values()), .001)


def construct_segments(raw, exclusive, *, min_coverage=.55):
    """Build per-speaker utterances from real aligned word timestamps.

    A speaker switch produces a new segment, even within one Whisper segment.
    """
    labels = sorted({t["label"] for t in exclusive})
    mapping = {label: i for i, label in enumerate(labels)}
    unknown_id = len(labels)
    segments, qa = [], []

    def flush(group, source):
        if not group:
            return
        start = group[0]["start"]
        end = group[-1]["end"]
        if end <= start:
            return
        text = "".join(w["text"] for w in group).strip()
        if not text:
            return
        votes = defaultdict(float)
        for word in group:
            votes[word["speaker"]] += word["end"] - word["start"]
        sid = max(votes, key=votes.get)
        uncertain = (sid == unknown_id or len(votes) > 1 or
                     any(w["coverage"] < min_coverage or w["share"] < .75 for w in group) or
                     source.get("alignment_status") != "whisperx_aligned" or
                     float(source.get("avg_logprob", 0)) < -.85 or
                     float(source.get("no_speech_prob", 0)) > .6 or
                     end - start < .5)
        # This is a conservative QA score, NOT a claimed ASR probability.
        qa_score = .4 if uncertain else .8
        idx = len(segments)
        segments.append(Segment(index=idx, start=round(start, 3),
                                end=round(end, 3), speaker=sid,
                                text_src=text, confidence=qa_score,
                                needs_review=uncertain))
        qa.append({"index": idx, "speaker_label": next(
            (label for label, assigned in mapping.items() if assigned == sid), "UNKNOWN"),
            "whisper_id": source.get("id"),
            "alignment_status": source.get("alignment_status"),
            "speaker_coverage_min": round(min(w["coverage"] for w in group), 3),
            "speaker_vote_share_min": round(min(w["share"] for w in group), 3),
            "needs_review": uncertain,
            "confidence_is_calibrated": False})

    for original in raw:
        words = original.get("words") or [{"start": original["start"],
                 "end": original["end"], "word": original["text"]}]
        group = []
        for word in words:
            a, b = word.get("start"), word.get("end")
            if a is None or b is None or float(b) <= float(a):
                continue
            a, b = float(a), float(b)
            label, coverage, share = assign_speaker(a, b, exclusive)
            sid = mapping[label] if label is not None else unknown_id
            unit = {"start": a, "end": b, "speaker": sid,
                    "coverage": coverage, "share": share,
                    "text": str(word.get("word") or "")}
            if group and (group[-1]["speaker"] != sid or
                          a - group[-1]["end"] > .8 or b - group[0]["start"] > 9.):
                flush(group, original)
                group = []
            group.append(unit)
        flush(group, original)
    if not segments:
        raise RuntimeError("Whisper+pyannote produced no speech segments")
    return segments, qa, mapping


class WhisperPyannoteAdapter:
    def __init__(self, model="large-v3-turbo", token="", device="auto",
                 compute_type="auto", forced_alignment=True):
        self.model = model
        self.token = token or os.getenv("HF_TOKEN", "")
        self.device = device
        self.compute_type = compute_type
        self.forced_alignment = forced_alignment
        self.last_evidence = {}

    def transcribe(self, wav_path):
        if not self.token:
            raise RuntimeError("Chưa cấu hình HF_TOKEN cho pyannote Community-1. "
                               "Hãy chấp nhận điều khoản model và cấp token Read.")
        wav_path = Path(wav_path)
        if not wav_path.is_file():
            raise FileNotFoundError(wav_path)
        try:
            from faster_whisper import WhisperModel
            from pyannote.audio import Pipeline
        except ImportError as exc:
            raise RuntimeError("Chưa cài whisper/pyannote. Cài: "
                               "pip install -r requirements-asr-hybrid.txt") from exc
        import torch
        dev = ("cuda" if torch.cuda.is_available() else "cpu") if self.device == "auto" else self.device
        compute = ("float16" if dev == "cuda" else "int8") if self.compute_type == "auto" else self.compute_type
        model = WhisperModel(self.model, device=dev, compute_type=compute)
        stream, info = model.transcribe(str(wav_path), beam_size=5, multilingual=True,
                                        word_timestamps=True, vad_filter=True,
                                        condition_on_previous_text=False)
        raw = [
            {"id": i, "start": float(p.start), "end": float(p.end), "text": p.text,
             "avg_logprob": float(p.avg_logprob), "no_speech_prob": float(p.no_speech_prob),
             "words": [{"start": w.start, "end": w.end, "word": w.word}
                       for w in (p.words or [])]}
            for i, p in enumerate(stream)]
        if not raw:
            raise RuntimeError("Whisper chưa nhận diện được lời thoại nào")
        del model
        pipe = Pipeline.from_pretrained("pyannote/speaker-diarization-community-1",
                                        token=self.token)
        if dev == "cuda":
            pipe.to(torch.device("cuda"))
        result = pipe(str(wav_path))
        exclusive = annotation_windows(result.exclusive_speaker_diarization)
        if not exclusive:
            raise RuntimeError("pyannote không phát hiện người nói nào")
        stats = {"method": "disabled", "aligned": 0,
                 "fallback_to_whisper_words": len(raw)}
        aligned = [{**x, "alignment_status": "whisper_words_unaligned"} for x in raw]
        if self.forced_alignment:
            aligned, stats = forced_align(raw, wav_path, device=dev)
        segments, qa, mapping = construct_segments(aligned, exclusive)
        self.last_evidence = {
            "source": "whisper_pyannote_community_1",
            "language_detected": getattr(info, "language", ""),
            "speaker_mapping": mapping,
            "diarized_turns": exclusive,
            "alignment": stats,
            "qa": qa,
            "qa_status": "UNAPPROVED",
            "human_verified": False}
        log.info("Hybrid ASR: %d sentences / %d speakers / %d review; alignment %d/%d",
                 len(segments), len(mapping), sum(s.needs_review for s in segments),
                 stats["aligned"], len(raw))
        return segments
