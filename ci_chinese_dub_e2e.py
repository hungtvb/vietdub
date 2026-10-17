#!/usr/bin/env python3
"""Real Mandarin FunASR -> local Chinese-Vietnamese MT -> Edge-TTS -> video QA.

The resulting media is UNAPPROVED until a human reviews transcript, Vietnamese
translation, individual voices, scene timing and audio naturalness.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import numpy as np
import soundfile as sf
from project.schema import Segment
from asr.dub_grouping import group_for_vietnamese_dub
from tts.edge_tts import EdgeTTS
from media.subs import write_srt
from media.mix import mix

MODEL_ID = "Helsinki-NLP/opus-mt-zh-vi"
VI_VOICE = "vi-VN-HoaiMyNeural"

def probe(path):
    data = json.loads(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_type:format=duration", "-of", "json", str(path)],
        text=True))
    streams = {s["codec_type"] for s in data["streams"]}
    duration = float(data["format"]["duration"])
    if not {"audio", "video"}.issubset(streams) or not math.isfinite(duration):
        raise RuntimeError("Source/output video must contain valid audio and video")
    return duration, streams

def verify_source(asr, video, duration):
    if (asr.get("status") != "CHINESE_FUNASR_REAL_ASR_COMPLETE"
            or asr.get("model_backend") != "automodel"
            or asr.get("qa", {}).get("qa_status") != "UNAPPROVED"):
        raise ValueError("Actual full FunASR AutoModel unapproved transcript required")
    digest = hashlib.sha256(Path(video).read_bytes()).hexdigest()
    if asr.get("source_video_sha256") != digest:
        raise ValueError("ASR source video SHA256 mismatch")
    items = [Segment.from_dict(x) for x in asr.get("real_transcript", [])]
    if not items or len(items) != asr.get("segment_count"):
        raise ValueError("ASR transcript missing or line count inconsistent")
    for i, seg in enumerate(items):
        if (seg.index != i or not math.isfinite(seg.start)
                or not math.isfinite(seg.end) or seg.start < 0
                or not seg.start < seg.end <= duration + .3
                or not seg.text_src.strip()):
            raise ValueError("ASR line index, timing or content invalid")
        seg.needs_review = True
        seg.source_lang = "zh"
    return items

def translate(segments):
    from transformers import MarianMTModel, MarianTokenizer
    import torch
    tokenizer = MarianTokenizer.from_pretrained(MODEL_ID)
    model = MarianMTModel.from_pretrained(MODEL_ID)
    model.eval()
    out = []
    for start in range(0, len(segments), 8):
        group = [x.text_src for x in segments[start:start + 8]]
        encoded = tokenizer(group, return_tensors="pt", padding=True,
                            truncation=True, max_length=256)
        with torch.inference_mode():
            decoded = model.generate(**encoded, num_beams=4, max_new_tokens=160)
        out += tokenizer.batch_decode(decoded, skip_special_tokens=True)
    if len(out) != len(segments):
        raise ValueError("Translation lost source lines")
    flags = []
    for seg, translated in zip(segments, out):
        translated = " ".join(translated.split()).strip()
        if not translated or translated == seg.text_src:
            raise ValueError("Empty or untranslated Vietnamese line")
        if any("\u3400" <= ch <= "\u9fff" for ch in translated):
            flags.append(seg.index)
        seg.text_vi = translated
        seg.gender = "female"  # fixed demo voice, NOT verified speaker identity
        seg.needs_review = True
    return {"model": MODEL_ID, "provider": "local_marian_mt",
            "human_approved": False, "suspected_untranslated_line_ids": flags}

def tempo_filter(factor):
    if not math.isfinite(factor) or factor <= 0:
        raise ValueError("Invalid speed ratio")
    chain = []
    while factor > 2.0:
        chain.append("atempo=2.0")
        factor /= 2.0
    while factor < .5:
        chain.append("atempo=0.5")
        factor /= .5
    return ",".join(chain + [f"atempo={factor:.6f}"])

def fit_voices(segments, target):
    stats = []
    for seg in segments:
        path = Path(seg.audio_vi)
        if not path.is_file() or path.stat().st_size < 2048:
            raise RuntimeError(f"Real Edge-TTS file missing: line {seg.index}")
        raw_duration = sf.info(path).duration
        window = seg.end - seg.start
        if raw_duration <= .03:
            raise ValueError("Silent or empty TTS clip")
        required = raw_duration / window
        # Reserve 3% margin to avoid cutting last syllables on placement.
        speed = max(1.0, required * 1.03)
        fitted = target / f"fitted_{seg.index:04d}.wav"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(path),
                        "-af", tempo_filter(speed), "-ar", "44100",
                        "-ac", "1", "-c:a", "pcm_s16le", str(fitted)], check=True)
        info = sf.info(fitted)
        if info.duration > window + .08:
            raise ValueError("Dubbing overruns allotted dialogue time")
        signal, _ = sf.read(fitted, dtype="float32")
        rms = float(np.sqrt(np.mean(signal.astype("float64") ** 2)))
        if not math.isfinite(rms) or rms < .0008:
            raise ValueError("TTS has inaudible or broken waveform")
        seg.audio_vi = str(fitted)
        stats.append({"id": seg.index, "original_tts_seconds": round(raw_duration, 3),
                      "time_slot_seconds": round(window, 3),
                      "fitted_tts_seconds": round(info.duration, 3),
                      "required_speed_factor": round(required, 3),
                      "voice_naturalness_review": required > 1.25,
                      "rms": round(rms, 5)})
    return {"voice": VI_VOICE, "real_audio_files": len(stats),
            "failed_audio_files": 0, "speed_review_count": sum(
                x["voice_naturalness_review"] for x in stats),
            "max_speed_factor": max(x["required_speed_factor"] for x in stats),
            "per_line": stats, "human_voice_identity_verified": False}

def render_clip(video, out, segments, duration):
    from tts.duration_fit import build_track
    write_srt(segments, out / "chinese_source.srt", field="text_src")
    srt = write_srt(segments, out / "vietnamese_review.srt")
    dub = build_track(segments, out / "dub.wav", duration)
    original = out / "original.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(video),
                    "-vn", "-ar", "44100", "-ac", "2", str(original)], check=True)
    mixed = mix(dub, original, out / "mixed.wav",
                dub_volume=1.0, orig_volume=.12)
    output = out / "chinese_vidub_UNAPPROVED.mp4"
    # Explicit H264 encoding: the original WebM video codec may not mux to MP4.
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(video),
                    "-i", str(mixed), "-map", "0:v:0", "-map", "1:a:0",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
                    "-shortest", str(output)], check=True)
    rendered_duration, streams = probe(output)
    if abs(rendered_duration - duration) > .7:
        raise ValueError("Rendered video/audio duration drift greater than 700ms")
    wave, _ = sf.read(mixed, dtype="float32")
    peak = float(np.max(np.abs(wave)))
    rms = float(np.sqrt(np.mean(wave.astype("float64") ** 2)))
    if peak >= 1.0 or rms < .0008 or output.stat().st_size < 20000:
        raise ValueError("Clipping, near-silent mix or empty rendered video")
    return {"file": str(output), "size_bytes": output.stat().st_size,
            "input_seconds": round(duration, 3),
            "output_seconds": round(rendered_duration, 3),
            "drift_seconds": round(rendered_duration - duration, 3),
            "audio_peak": round(peak, 4), "audio_rms": round(rms, 5),
            "streams": sorted(streams)}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--asr-report", required=True)
    parser.add_argument("--out", default="chinese_dub")
    opts = parser.parse_args()
    out = Path(opts.out)
    out.mkdir(parents=True, exist_ok=True)
    evidence = {"status": "RUNNING", "human_approved": False,
                "tts_provider": "Edge-TTS", "content_accuracy_measured": False}
    try:
        video = Path(opts.video)
        duration, _ = probe(video)
        asr = json.loads(Path(opts.asr_report).read_text(encoding="utf-8"))
        source = verify_source(asr, video, duration)
        segments, source_mapping = group_for_vietnamese_dub(source)
        evidence.update(source_sha256=asr["source_video_sha256"],
                        asr_segment_count=len(source),
                        dub_segment_count=len(segments),
                        asr_review_count=asr["review_required_count"],
                        asr_accuracy_measured=False,
                        dub_grouping={"method": "speaker_and_time_scoped_semantic_windows",
                                      "source_asr_lines": len(source),
                                      "dub_units": len(segments),
                                      "original_id_mapping": source_mapping,
                                      "human_verified": False},
                        translation=translate(segments))
        EdgeTTS(voice_female=VI_VOICE, concurrency=2, retries=2).synthesize(
            segments, out / "tts")
        evidence["tts"] = fit_voices(segments, out)
        evidence["video"] = render_clip(video, out, segments, duration)
        evidence["status"] = "RENDERED_TECHNICALLY_REVIEW_REQUIRED"
        evidence["technical_pass"] = True
        evidence["voice_naturalness_quality_pass"] = (
            evidence["tts"]["speed_review_count"] == 0)
        evidence["overall_quality_pass"] = False  # no human translation/voice review
        evidence["quality_flags"] = {
            "translation_unverified": True, "asr_unverified": True,
            "speaker_identity_unverified": True,
            "speed_review": evidence["tts"]["speed_review_count"],
            "possible_chinese_untranslated": len(
                evidence["translation"]["suspected_untranslated_line_ids"])}
        (out / "review_lines.json").write_text(json.dumps(
            [s.to_dict() for s in segments], ensure_ascii=False, indent=2),
            encoding="utf-8")
        print("REAL_CHINESE_VI_EDGETTS_MP4_OK", len(segments))
    except Exception as exc:
        evidence["status"] = "FAILED"
        evidence["error"] = f"{type(exc).__name__}: {str(exc)[:500]}"
        raise
    finally:
        (out / "qa.json").write_text(json.dumps(
            evidence, ensure_ascii=False, indent=2), encoding="utf-8")

if __name__ == "__main__":
    main()
