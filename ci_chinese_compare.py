#!/usr/bin/env python3
"""Chinese audio comparison: existing full FunASR run vs real Whisper ASR.

The video and earlier FunASR result are external CI artifacts. Neither is
hardcoded into the ASR modules; arguments specify any Chinese video.
Agreement != accuracy. No WER/CER until ground-truth subtitles are reviewed.
"""
import argparse
import json
import subprocess
import time
from pathlib import Path

from asr.chinese_comparison import compare_transcripts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--funasr-report", required=True)
    parser.add_argument("--out", default="comparison/report.json")
    parser.add_argument("--model", default="small")
    parser.add_argument("--seconds", type=float, default=30.)
    parser.add_argument("--cpu-threads", type=int, default=4)
    args = parser.parse_args()
    original = json.loads(Path(args.funasr_report).read_text(encoding="utf-8"))
    if original.get("status") != "CHINESE_FUNASR_REAL_ASR_COMPLETE":
        raise RuntimeError("A successfully completed REAL FunASR transcript is required")
    funasr = original["real_transcript"]
    if not funasr:
        raise RuntimeError("No real FunASR segments to compare")
    from faster_whisper import WhisperModel
    destination = Path(args.out)
    destination.parent.mkdir(parents=True, exist_ok=True)
    cropped = destination.parent / "test_audio_16k.wav"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-i", str(args.video), "-t", str(args.seconds),
        "-vn", "-ac", "1", "-ar", "16000", str(cropped)], check=True)
    t0 = time.perf_counter()
    model = WhisperModel(args.model, device="cpu", compute_type="int8",
                         cpu_threads=args.cpu_threads)
    model_load_seconds = time.perf_counter() - t0
    t1 = time.perf_counter()
    stream, info = model.transcribe(
        str(cropped), language="zh", beam_size=5,
        vad_filter=True, word_timestamps=False,
        condition_on_previous_text=False)
    whisper = [
        {"start": float(s.start), "end": float(s.end), "text": s.text}
        for s in stream
    ]
    transcribe_seconds = time.perf_counter() - t1
    if not whisper:
        raise RuntimeError("Whisper produced no Mandarin transcript")
    compare = compare_transcripts(
        funasr, whisper, duration=args.seconds,
        window_seconds=10.)
    report = {
        "status": "REAL_MANDARIN_CROSS_MODEL_COMPARISON_COMPLETE",
        "source_video": str(args.video),
        "comparison_duration_seconds": args.seconds,
        "human_reference_verified": False,
        "reported_metric_is_accuracy": False,
        "funasr_source": {
            "backend": "modelscope",
            "original_full_audio_seconds": 91.821,
            "original_run_asr_seconds": original.get("asr_elapsed_seconds"),
            "total_segments": len(funasr),
        },
        "whisper_model": args.model,
        "whisper_detected_language": info.language,
        "whisper_model_load_seconds": round(model_load_seconds, 3),
        "whisper_inference_seconds": round(transcribe_seconds, 3),
        "whisper_realtime_factor": round(
            transcribe_seconds / max(args.seconds, .01), 4),
        "whisper_segments": whisper,
        "agreement": compare,
        "warnings": [
            "Different full-run and short-run durations: do NOT compare their "
            "raw inference times as a same-clip speed benchmark.",
            "Model disagreement identifies review candidates; it is not CER/WER.",
        ],
    }
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "whisper_segments": len(whisper),
        "whisper_model_load_seconds": report["whisper_model_load_seconds"],
        "whisper_inference_seconds": report["whisper_inference_seconds"],
        "cross_model_agreement": compare["cross_model_agreement"],
        "disagreement_windows": compare["disagreement_windows"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
