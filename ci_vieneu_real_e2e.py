"""Real, unmocked VieNeu v3 Turbo CPU ONNX inference + MP4 transport smoke.

Synthetic video (not a film or dubbing-accuracy benchmark). Artifacts and
timings are observable evidence, not listening or speaker-identity approval.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

import soundfile as sf

from project.schema import Segment
from tts.vieneu_tts import VieNeuTTS

OUTPUT = Path("ci-vieneu-real")
OUTPUT.mkdir(exist_ok=True)
DATA = {"model": "VieNeu-TTS v3 Turbo", "backend": "onnx", "precision": "fp32",
        "real_weights": True, "human_approved": False,
        "video_source": "generated color chart; not a real movie"}


def run(command):
    p = subprocess.run(command, capture_output=True, text=True, timeout=120)
    if p.returncode:
        raise RuntimeError("Failed command: " + " ".join(command) + ": " + p.stderr[-800:])
    return p


def main():
    try:
        seg = Segment(
            index=0, start=0.0, end=12.0, speaker=0, gender="female",
            text_src="你好，这是一段语音测试。",
            text_vi="Xin chào, đây là bài kiểm tra lồng tiếng Việt bằng mô hình VieNeu."
        )
        start = time.perf_counter()
        provider = VieNeuTTS(backend="onnx", precision="fp32",
                             voice_female="Mai Anh")
        provider.synthesize([seg], OUTPUT / "tts")
        DATA["elapsed_sec"] = round(time.perf_counter()-start, 3)
        audio = Path(seg.audio_vi)
        if not audio.exists():
            raise RuntimeError("No real synthesized WAV produced")
        info = sf.info(audio)
        DATA["audio"] = {
            "frames": info.frames, "samplerate": info.samplerate,
            "channels": info.channels, "duration_sec": round(info.duration, 3),
            "bytes": audio.stat().st_size,
        }
        if info.samplerate != 44100 or info.channels != 1 or info.duration < 0.25:
            raise RuntimeError("Invalid resampled WAV")
        if not shutil.which("ffmpeg"):
            raise RuntimeError("ffmpeg is missing")
        mp4 = OUTPUT / "vieneu_real_tts_synthetic_video.mp4"
        run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
             "-i", "color=c=0x132235:s=640x360:r=25:d=12",
             "-i", str(audio), "-c:v", "libx264", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "128k", "-t", "12", "-movflags",
             "+faststart", str(mp4)])
        DATA["output_mp4_bytes"] = mp4.stat().st_size
        DATA["status"] = "PASS_SYNTHETIC_VIDEO_REAL_TTS"
        print(json.dumps(DATA, ensure_ascii=False, indent=2))
    except Exception as exc:
        DATA["status"] = "FAIL"
        DATA["error"] = type(exc).__name__ + ": " + str(exc)
        print(json.dumps(DATA, ensure_ascii=False, indent=2))
        raise
    finally:
        (OUTPUT / "qa.json").write_text(json.dumps(
            DATA, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
