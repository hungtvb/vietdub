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


def _stage_safe_onnx_files(precision: str):
    """Stage real ONNX graph + external data beside each other without symlinks.

    Hugging Face's shared snapshot cache uses symlinks to distinct blobs.
    ONNX Runtime correctly rejects a model whose external-data path escapes
    the directory containing its graph. Use a private, real-file copy rather
    than disabling that security validation.
    """
    from huggingface_hub import hf_hub_download
    from vieneu._v3_turbo_engine.onnx_runtime_lite import (
        _V3_REPO, _CODEC_REPO, _GRAPH_FILES, _CODEC_FILES
    )
    from core.settings import settings_path
    base = settings_path().parent / "models" / "vieneu-onnx"
    folder = "onnx_int8" if precision == "int8" else "onnx_update"
    graph_dir = base / folder
    codec_dir = base / "codec"
    for repo, filenames, subfolder, root in (
        (_V3_REPO, _GRAPH_FILES, folder, graph_dir),
        (_CODEC_REPO, _CODEC_FILES, None, codec_dir),
    ):
        root.mkdir(parents=True, exist_ok=True)
        for filename in filenames:
            try:
                path = Path(hf_hub_download(
                    repo_id=repo, filename=filename,
                    subfolder=subfolder, local_dir=str(root.parent if subfolder else root)
                ))
            except Exception:
                # Upstream marks only optional JSON metadata as absent.
                if filename == "codec_browser_onnx_meta.json":
                    continue
                raise
            expected = root / filename
            # local_dir may contain files in a subfolder; ensure path matches.
            if path != expected:
                raise VieNeuTTSError(
                    f"VieNeu model path mismatch: {path} != {expected}")
            # An actual copy is required: ONNX graph and .data must resolve
            # within the same real directory, not separate HF blob dirs.
            if path.is_symlink():
                import shutil
                staged = path.with_name(path.name + ".real-copy")
                shutil.copyfile(path, staged)
                staged.replace(path)
            if not path.is_file() or path.stat().st_size == 0:
                raise VieNeuTTSError(f"VieNeu model artifact missing: {path}")
            if path.resolve().parent != root.resolve():
                raise VieNeuTTSError(f"Unsafe VieNeu external-data path: {path}")
    return graph_dir, codec_dir


@lru_cache(maxsize=2)
def _load_engine(backend: str, precision: str):
    try:
        from vieneu import Vieneu
    except ImportError as exc:
        raise VieNeuTTSError(
            "Chưa cài VieNeu-TTS. Chạy: pip install -r requirements-vieneu.txt"
        ) from exc
    try:
        use_onnx = backend == "onnx"
        if backend == "auto":
            try:
                import torch
                use_onnx = not torch.cuda.is_available()
            except ImportError:
                use_onnx = True
        if use_onnx:
            from unittest.mock import patch
            from vieneu._v3_turbo_engine.onnx_runtime_lite import (
                OnnxV3LiteEngine, _CODEC_REPO
            )
            graph, codec = _stage_safe_onnx_files(precision)
            upstream_fetch = OnnxV3LiteEngine._fetch

            # The installed SDK forwards onnx_dir but does not expose
            # codec_dir through Vieneu(...). Override only codec lookup,
            # while holding the provider's engine-init lock. This is a
            # temporary compatibility layer until SDK adds codec_dir.
            def fetch_codec(repo, files, subfolder):
                if repo == _CODEC_REPO and subfolder is None:
                    return codec
                return upstream_fetch(repo, files, subfolder)

            with _ENGINE_LOCK, patch.object(
                OnnxV3LiteEngine, "_fetch", staticmethod(fetch_codec)
            ):
                return Vieneu(
                    mode="v3turbo", backend="onnx", precision=precision,
                    onnx_dir=str(graph),
                )
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
