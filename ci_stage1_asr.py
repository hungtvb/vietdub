#!/usr/bin/env python3
"""Real multilingual Whisper ASR with word timestamps and existing real speaker IDs.

Speaker assignment transfers earlier FunASR diarization by word-time overlap.
Ambiguous words are flagged for human review, never silently marked reliable.
"""
import argparse
import json
import logging
import os
from pathlib import Path

from project.schema import Segment, Speaker

log = logging.getLogger("vietdub.whisper_ci")


def overlap_speaker(start, end, reference):
    votes = {}
    for item in reference:
        length = max(0., min(end, item.end) - max(start, item.start))
        if length:
            votes[item.speaker] = votes.get(item.speaker, 0.) + length
    if votes:
        ranks = sorted(votes.items(), key=lambda x: x[1], reverse=True)
        sid, duration = ranks[0]
        second = ranks[1][1] if len(ranks) > 1 else 0.
        return sid, min(1., duration / max(end-start, .001)), second / max(duration, .001)
    nearest = min(reference, key=lambda item: min(abs(start-item.end), abs(end-item.start)))
    distance = min(abs(start-nearest.end), abs(end-nearest.start))
    return (nearest.speaker, 0., 0.) if distance < 2. else (-1, 0., 1.)


def convert(raw, reference, speakers):
    if not reference or not speakers:
        raise RuntimeError("Real reference diarization required")
    lines, checks = [], []
    unknown_id = max(speakers) + 1

    def flush(words, source):
        if not words:
            return
        text = "".join(w["text"] for w in words).strip()
        if not text:
            return
        start, end = words[0]["start"], words[-1]["end"]
        if end <= start:
            return
        speaker = max(set(w["speaker"] for w in words),
                      key=lambda sid: sum(w["end"]-w["start"] for w in words if w["speaker"] == sid))
        ambiguous = (len(set(w["speaker"] for w in words)) > 1 or
                     any(w["coverage"] < .35 or w["ambiguity"] > .35 for w in words) or
                     float(source.get("avg_logprob", 0)) < -.85 or
                     float(source.get("no_speech_prob", 0)) > .6 or speaker == -1)
        if speaker == -1:
            speaker = unknown_id
            speakers.setdefault(speaker, Speaker(id=speaker))
        item = Segment(index=len(lines), start=round(start, 3), end=round(end, 3),
                       speaker=speaker, gender=speakers[speaker].gender,
                       text_src=text, confidence=1., needs_review=ambiguous)
        lines.append(item)
        checks.append(dict(index=item.index, review=ambiguous,
                           avg_logprob=source.get("avg_logprob"),
                           no_speech_prob=source.get("no_speech_prob"),
                           original_whisper_id=source.get("id")))

    for item in raw:
        words = item.get("words") or [dict(start=item["start"], end=item["end"], word=item["text"])]
        group = []
        for word in words:
            a, b = float(word["start"]), float(word["end"])
            if b <= a:
                continue
            sid, coverage, ambiguity = overlap_speaker(a, b, reference)
            w = dict(start=a, end=b, text=str(word["word"]), speaker=sid,
                     coverage=coverage, ambiguity=ambiguity)
            if group and (sid != group[-1]["speaker"] or a-group[-1]["end"] > .8 or
                          b-group[0]["start"] > 9.):
                flush(group, item)
                group = []
            group.append(w)
        flush(group, item)
    if not lines:
        raise RuntimeError("Whisper returned no real lines")
    return lines, checks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=os.environ.get("WHISPER_MODEL", "large-v3-turbo"))
    parser.add_argument("--reference", default="prior_asr/asr-handoff.json")
    parser.add_argument("--input", default="private_input/input.mp4")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    legacy = json.loads(Path(args.reference).read_text(encoding="utf-8"))
    reference = [Segment.from_dict(x) for x in legacy["segments"]]
    speakers = {x["id"]: Speaker.from_dict(x) for x in legacy["speakers"]}
    if not Path(args.input).is_file():
        raise FileNotFoundError(args.input)
    from faster_whisper import WhisperModel
    model = WhisperModel(args.model, device="cpu", compute_type="int8",
                         cpu_threads=4, num_workers=2)
    # Critical: multilingual=True detects code switching per model window.
    stream, info = model.transcribe(args.input, beam_size=5,
                                   multilingual=True, word_timestamps=True,
                                   vad_filter=True,
                                   vad_parameters=dict(min_silence_duration_ms=400),
                                   condition_on_previous_text=False,
                                   hallucination_silence_threshold=1.0)
    raw = []
    for i, item in enumerate(stream):
        raw.append(dict(id=i, start=item.start, end=item.end, text=item.text,
                        avg_logprob=item.avg_logprob, no_speech_prob=item.no_speech_prob,
                        words=[dict(start=w.start, end=w.end, word=w.word)
                               for w in (item.words or [])]))
    lines, checks = convert(raw, reference, speakers)
    out = Path("output")
    out.mkdir(exist_ok=True)
    payload = dict(schema_version=1, source="real_whisper_" + args.model,
                   metadata=dict(initial_detected_language=info.language,
                                 language_detection="multilingual_per_window",
                                 speaker_source="real_funasr_previous_ci",
                                 speaker_assignment="word_time_overlap_unverified",
                                 review_count=sum(s.needs_review for s in lines)),
                   segments=[s.to_dict() for s in lines],
                   speakers=[s.to_dict() for s in speakers.values()])
    (out/"asr-handoff.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (out/"whisper-raw-and-qa.json").write_text(json.dumps(dict(raw=raw, qa=checks), ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("REAL Whisper %s: %d raw -> %d lines, %d to review, %d speaker IDs",
             args.model, len(raw), len(lines), payload["metadata"]["review_count"], len(speakers))


if __name__ == "__main__":
    main()
