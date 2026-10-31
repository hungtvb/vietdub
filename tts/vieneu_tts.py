# VietDub - Vietnamese dubbing for Chinese videos (PySide6 desktop app)
# Copyright (C) 2026 VietDub contributors
# License: GNU General Public License v3.0 (see LICENSE)
"""Optional VieNeu-TTS v3 Turbo provider. Output is always 44.1 kHz mono WAV.

The SDK and model are NOT bundled: install requirements-vieneu.txt separately.
Model loading is lazy and shared between jobs/preview; calls are serialized to
avoid competing GPU/CPU inference on the same engine.
"""
from __future__ import annotations

import hashlib
import logging
import subprocess
import threading
from functools import lru_cache
from pathlib import Path
from typing import Callable, List, Optional

import soundfile as sf

from media import _bin
from project.schema import Segment

log = logging.getLogger("vietdub.vieneu_tts")
_ENGINE_LOCK = threading.RLock()
TARGET_RATE = 44100


class VieNeuTTSError(RuntimeError):
    """VieNeu is unavailable or a sentence cannot be synthesized."""


@lru_cache(maxsize=2)
def _load_engine(backend: str, precision: str):
    try:
        from vieneu import Vieneu
    except ImportError as exc:
        raise VieNeuTTSError(
            "Chưa cài VieNeu-TTS. Chạy: pip install -r requirements-vieneu.txt"
        ) from exc
    try:
        return Vieneu(mode="v3turbo", backend=backend, precision=precision)
    except Exception as exc:
        raise VieNeuTTSError(f"Không tải được mô hình VieNeu v3 Turbo: {exc}") from exc


def _valid_wav(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size < 1024:
        return False
    try:
        info = sf.info(str(path))
        return info.frames > 0 and info.samplerate == TARGET_RATE and info.channels == 1
    except (OSError, RuntimeError, ValueError):
        return False


def _cache_key(text: str, voice: str, backend: str, precision: str) -> str:
    # Same .md5 manifest as Edge-TTS, but provider-prefixed: switching engines
    # always invalidates the previous sentence's WAV (even with the same name).
    payload = f"vieneu-v3turbo|{backend}|{precision}|{voice}|{text}"
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


class VieNeuTTS:
    """Drop-in synthesize(segments, out_dir) interface for tts.edge_tts.EdgeTTS."""

    def __init__(self, voice_male: str = "Hải Đăng",
                 voice_female: str = "Mai Anh",
                 backend: str = "auto", precision: str = "fp32",
                 engine_factory: Optional[Callable] = None):
        if backend not in ("auto", "onnx", "pytorch"):
            raise ValueError(f"VieNeu backend không hợp lệ: {backend}")
        if precision not in ("fp32", "int8"):
            raise ValueError(f"VieNeu precision không hợp lệ: {precision}")
        self.voice_male = voice_male
        self.voice_female = voice_female
        self.backend = backend
        self.precision = precision
        self._engine_factory = engine_factory or _load_engine

    def voice_for(self, gender: str) -> str:
        return self.voice_female if gender == "female" else self.voice_male

    def synthesize(self, segments: List[Segment], out_dir: str | Path,
                   progress_cb: Optional[Callable[[int, int], None]] = None
                   ) -> List[Segment]:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        todo = []
        for seg in segments:
            text = (seg.text_vi or seg.text_src or "").strip()
            dest = out_dir / f"seg_{seg.index:04d}.wav"
            key_path = dest.with_suffix(".md5")
            key = _cache_key(text, self.voice_for(seg.gender),
                             self.backend, self.precision)
            if text and _valid_wav(dest) and key_path.is_file() \
                    and key_path.read_text(encoding="utf-8").strip() == key:
                seg.audio_vi = str(dest)
                continue
            seg.audio_vi = ""
            if text:
                todo.append((seg, text, dest, key_path, key))
        if not todo:
            if progress_cb:
                progress_cb(len(segments), len(segments))
            return segments

        # Load only for a non-cached sentence. Keep each completed sentence
        # checkpointed, so retry does not repeat already-successful inference.
        with _ENGINE_LOCK:
            engine = self._engine_factory(self.backend, self.precision)
            for n, (seg, text, dest, key_path, key) in enumerate(todo, 1):
                native = dest.with_suffix(".native.tmp.wav")
                converted = dest.with_suffix(".converted.tmp.wav")
                try:
                    # A failed request may leave an old WAV; never let that
                    # become a silent fallback in duration_fit.
                    dest.unlink(missing_ok=True)
                    key_path.unlink(missing_ok=True)
                    audio = engine.infer(text, voice=self.voice_for(seg.gender))
                    engine.save(audio, str(native))
                    if not native.is_file() or native.stat().st_size < 1024:
                        raise RuntimeError("mô hình tạo file audio rỗng")
                    p = subprocess.run(
                        [_bin.ffmpeg_cmd(), "-y", "-v", "error", "-i", str(native),
                         "-ar", str(TARGET_RATE), "-ac", "1", "-c:a", "pcm_s16le",
                         str(converted)],
                        capture_output=True, text=True, timeout=120)
                    if p.returncode != 0 or not _valid_wav(converted):
                        raise RuntimeError(f"chuyển WAV 44.1 kHz thất bại: {p.stderr[:200]}")
                    converted.replace(dest)
                    # Manifest is written after WAV is safely in place.
                    key_path.write_text(key, encoding="utf-8")
                    seg.audio_vi = str(dest)
                    log.info("VieNeu TTS câu %s: %s", seg.index, self.voice_for(seg.gender))
                except Exception as exc:
                    dest.unlink(missing_ok=True)
                    key_path.unlink(missing_ok=True)
                    raise VieNeuTTSError(
                        f"VieNeu-TTS lỗi câu {seg.index}: {exc}. "
                        "Các câu đã xong được cache; có thể chạy lại bước TTS."
                    ) from exc
                finally:
                    native.unlink(missing_ok=True)
                    converted.unlink(missing_ok=True)
                if progress_cb:
                    progress_cb(n, len(todo))
        return segments
