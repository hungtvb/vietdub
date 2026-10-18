#!/usr/bin/env python3
"""Real Mandarin regression against a Commons-licensed source video.

This test NEVER uses fixture dialogue or claims a reference WER. All
transcripts come directly from FunASR on a downloaded Chinese news clip.
"""
from __future__ import annotations
import argparse
import json
import hashlib
import math
from difflib import SequenceMatcher
import subprocess
import time
from pathlib import Path

from asr.chinese_quality import qa_chinese_segments
from asr.engine_router import select_asr_engine
from asr.funasr_adapter import FunASRAdapter
from asr.source_language import detect_source_language


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("--video", required=True)
    cli.add_argument("--source-page", default="https://commons.wikimedia.org/wiki/File:【两会30秒】水庆霞：中国女足非世界顶级，但会不断追赶.webm")
    cli.add_argument("--source-label", default="Chinese football interview")
    cli.add_argument("--source-license", default="CC BY 3.0 (attribution: 中国新闻社)")
    cli.add_argument("--out", default="chinese_regression")
    cli.add_argument("--mode", choices=("smoke", "full", "benchmark", "boundary"), default="full")
    cli.add_argument("--backend", choices=("modelscope", "automodel"),
                     default="modelscope")
    cli.add_argument("--benchmark-seconds", type=float, default=25.)
    opts = cli.parse_args()
    root = Path(opts.out)
    root.mkdir(parents=True, exist_ok=True)
    video = Path(opts.video)
    if not video.is_file() or video.stat().st_size < 10000:
        raise RuntimeError("Real Mandarin source video is missing")
    wav = root / "chinese_source_16k.wav"
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error",
                    "-i", str(video), "-vn",
                    "-af", "aresample=async=1:first_pts=0",
                    "-ac", "1", "-ar", "16000",
                    str(wav)], check=True)
    if opts.mode in ("benchmark", "boundary"):
        if opts.benchmark_seconds < 5 or opts.benchmark_seconds > 180:
            raise ValueError("Benchmark duration must be between 5 and 180 seconds")
        short_wav = root / "benchmark_16k.wav"
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error",
                        "-i", str(wav), "-t", str(opts.benchmark_seconds),
                        "-ac", "1", "-ar", "16000", str(short_wav)], check=True)
        wav = short_wav
    from faster_whisper import WhisperModel
    detector = WhisperModel("tiny", device="cpu", compute_type="int8")
    language = detect_source_language(wav, detector)
    del detector
    route = select_asr_engine(language)
    report = {
        "source_video": "Wikimedia Commons: " + opts.source_label,
        "source_video_sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
        "source_page": opts.source_page,
        "license": opts.source_license,
        "language_detection": language.to_dict(),
        "automatic_route": route.to_dict(),
        "status": "LANGUAGE_PROBED" if opts.mode == "smoke" else "ASR_RUNNING",
        "model_backend": opts.backend,
        "model_timing_profiling_available": False,
        "human_transcript_verified": False,
        "model_quality_wer_measured": False,
    }
    if opts.mode in ("full", "benchmark", "boundary"):
        from core.settings import DEFAULTS
        model = FunASRAdapter(
            asr_model=DEFAULTS["asr_model"],
            vad_model=DEFAULTS["vad_model"],
            punc_model=DEFAULTS["punc_model"],
            spk_model=DEFAULTS["spk_model"],
            backend=opts.backend, ncpu=4, batch_size_s=60,
            max_vad_segment_ms=15000,
            keep_loaded=opts.mode == "boundary",
            chunk_overlap_sec=1.5)
        started = time.monotonic()
        segments = model.transcribe(wav)
        report["asr_elapsed_seconds"] = round(time.monotonic() - started, 2)
        report["asr_profile"] = dict(model.metrics)
        report["model_timing_profiling_available"] = True
        if not segments:
            raise AssertionError("FunASR produced no real transcript")
        if opts.mode == "boundary":
            from asr import funasr_adapter
            # Deliberately shrink the nominal ten-minute chunks on real
            # Chinese audio. Same pretrained model, same recording.
            # This specifically tests boundary-ownership in production code.
            full_hanzi = "".join(
                ch for seg in segments for ch in seg.text_src
                if "\u3400" <= ch <= "\u9fff")
            no_chunks_profile = dict(model.metrics)
            original_chunk_sec = funasr_adapter.ASR_CHUNK_SEC
            try:
                funasr_adapter.ASR_CHUNK_SEC = 8.
                chunked = model.transcribe(wav)
            finally:
                funasr_adapter.ASR_CHUNK_SEC = original_chunk_sec
            if not chunked or model.metrics["chunk_count"] < 2:
                raise AssertionError("Chunked ASR produced no actual chunks")
            chunk_hanzi = "".join(
                ch for seg in chunked for ch in seg.text_src
                if "\u3400" <= ch <= "\u9fff")
            char_agreement = SequenceMatcher(
                None, full_hanzi, chunk_hanzi, autojunk=False).ratio()
            report["long_video_boundary_test"] = {
                "method": "forced_8s_chunks_of_same_real_25s_audio",
                "original_segment_count": len(segments),
                "chunked_segment_count": len(chunked),
                "original_characters": len(full_hanzi),
                "chunked_characters": len(chunk_hanzi),
                "sequence_agreement_not_CER": round(char_agreement, 4),
                "baseline_performance": no_chunks_profile,
                "chunked_performance": dict(model.metrics),
                "chunked_transcript": [s.to_dict() for s in chunked],
                "human_reference_verified": False,
            }
            if (not all(-.01 <= s.start < s.end <= opts.benchmark_seconds + .25
                        for s in chunked)):
                raise AssertionError("Chunked timestamps escaped source duration")
            if char_agreement < .55:
                raise AssertionError(
                    f"Severe chunk boundary disagreement on Chinese video: {char_agreement:.3f}")
            report["status"] = "CHINESE_FUNASR_REAL_BOUNDARY_TEST_PASSED"
            report["original_asr_profile"] = no_chunks_profile
            segments = chunked
        qa = qa_chinese_segments(segments)
        han_count = sum(sum("\u3400" <= ch <= "\u9fff"
                            for ch in s.text_src) for s in segments)
        if han_count < 10:
            raise AssertionError(
                "FunASR output has too little Chinese text to be a useful test")
        for seg in segments:
            if not math.isfinite(seg.start) or not math.isfinite(seg.end):
                raise AssertionError("Nonfinite timestamp")
            if seg.start < 0 or seg.end <= seg.start:
                raise AssertionError("Bad timestamp range")
        report.update({
            "status": ("CHINESE_FUNASR_REAL_BOUNDARY_TEST_PASSED"
                       if opts.mode == "boundary" else
                       "CHINESE_FUNASR_BENCHMARK_COMPLETE"
                       if opts.mode == "benchmark"
                       else "CHINESE_FUNASR_REAL_ASR_COMPLETE"),
            "actual_hanzi_count": han_count,
            "segment_count": len(segments),
            "review_required_count": qa["review_required"],
            "real_transcript": [s.to_dict() for s in segments],
            "qa": qa,
        })
        print("REAL_MANDARIN_FUNASR_OK",
              len(segments), "utterances /", han_count, "Chinese glyphs")
    else:
        print("REAL_MANDARIN_LANGUAGE_PROBE_OK", route.engine, language.primary)
    (root / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "language_detected": language.primary,
        "confidence": language.confidence,
        "automatic_asr_route": route.engine,
        "test_mode": opts.mode}, ensure_ascii=False))


if __name__ == "__main__":
    main()
