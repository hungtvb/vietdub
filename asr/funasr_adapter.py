# VietDub - Vietnamese dubbing for Chinese videos (PySide6 desktop app)
# Copyright (C) 2026 VietDub contributors
# License: GNU General Public License v3.0 (see LICENSE)
#
# Adapted from pyVideoTrans (https://github.com/jianchang512/pyvideotrans)
# by jianchang512, GPL-3.0:
#   - process/stt_paraformer.py::paraformer() (SeacoParaformer + fsmn_vad +
#     ct-punc + cam++ speaker labels -> sentence_info)
#   - recognition/_base.py::_post_fix() (drop garbage lines, fix overlaps,
#     drop end<=start)
"""Step [2] - FunASR transcription + speaker diarization.

Combo (tested 2026-10-08, RTF 0.305 on CPU):
  SeacoParaformer (ASR) + fsmn-vad (segmentation) + ct-punc 290M
  (punctuation, light version) + cam++ (speaker labels).

Speaker labels come out as spk0/spk1/... and are mapped to integer ids.
"""
from __future__ import annotations

import logging
import math
import re
import shutil
import subprocess
import tempfile
import time
from threading import RLock
from pathlib import Path
from typing import List, Optional

from media import _bin
from project.schema import Segment

log = logging.getLogger("vietdub.asr")

# garbage line = only punctuation/symbols/whitespace (port of NON_WORD idea)
_NON_WORD = re.compile(r"^[^\w\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]+$", re.UNICODE)

# edge case 17: ASR processes the wav in chunks this long so a 90-minute
# film never sits in RAM as one giant tensor batch.
ASR_CHUNK_SEC = 10 * 60


def _models_dir() -> Path:
    """Thư mục tải model FunASR (lần đầu chạy, chỉ 1 lần, ~1.3GB).

    Windows: %APPDATA%/VietDub/models ; Linux/macOS: ~/.config/VietDub/models.
    Đặt qua biến môi trường MODELSCOPE_CACHE trước khi import modelscope —
    nếu user đã tự đặt MODELSCOPE_CACHE thì tôn trọng lựa chọn của họ.
    """
    from core.settings import settings_path

    d = settings_path().parent / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


class ASRError(Exception):
    pass


def _wav_duration_sec(wav_path: Path) -> float:
    import soundfile as sf
    info = sf.info(str(wav_path))
    return info.frames / float(info.samplerate)


class FunASRAdapter:
    def __init__(self, asr_model: str, vad_model: str, punc_model: str,
                 spk_model: str, device: str = "cpu",
                 backend: str = "modelscope", ncpu: int = 4,
                 batch_size_s: int = 60, max_vad_segment_ms: int = 15000,
                 keep_loaded: bool = False, chunk_overlap_sec: float = 1.5):
        if backend not in ("modelscope", "automodel"):
            raise ValueError("Unsupported Chinese ASR backend: " + backend)
        if ncpu < 1 or batch_size_s < 1 or max_vad_segment_ms < 1000:
            raise ValueError("Invalid Chinese ASR tuning configuration")
        if not 0. <= float(chunk_overlap_sec) <= 15.:
            raise ValueError("chunk_overlap_sec must be between 0 and 15")
        self.chunk_overlap_sec = float(chunk_overlap_sec)
        self.keep_loaded = bool(keep_loaded)
        self._inference_lock = RLock()
        self.backend = backend
        self.ncpu = ncpu
        self.batch_size_s = batch_size_s
        self.max_vad_segment_ms = max_vad_segment_ms
        self.asr_model = asr_model
        self.vad_model = vad_model
        self.punc_model = punc_model
        self.spk_model = spk_model
        self.device = device
        self._pipe = None
        self.metrics = {
            "backend": self.backend,
            "model_load_seconds": None,
            "inference_seconds": 0.0,
            "audio_seconds": 0.0,
            "total_seconds": None,
            "real_time_factor": None,
            "reused_loaded_model": False,
            "cache_dir": "",
            "chunk_count": 0,
            "chunk_overlap_seconds": self.chunk_overlap_sec,
            "boundary_review_count": 0,
        }
        self._started_at = None

    def load(self) -> None:
        """Load models once. Raises ASRError with a fix hint on failure."""
        if self._pipe is not None:
            self.metrics["reused_loaded_model"] = True
            self.metrics["model_load_seconds"] = 0.
            return
        load_started = time.perf_counter()
        # Model KHÔNG bundle trong exe: tải lần đầu về thư mục app data.
        # Phải đặt env TRƯỚC khi import modelscope (nó đọc env lúc import).
        import os

        models_dir = _models_dir()
        if not os.environ.get("MODELSCOPE_CACHE"):
            os.environ["MODELSCOPE_CACHE"] = str(models_dir)
            log.info("model FunASR sẽ tải về: %s", models_dir)
        self.metrics["cache_dir"] = os.environ.get("MODELSCOPE_CACHE", str(models_dir))
        def build_model():
            if self.backend == "automodel":
                from funasr import AutoModel
                return AutoModel(
                    model="paraformer-zh",
                    vad_model="fsmn-vad",
                    vad_kwargs={"max_single_segment_time": self.max_vad_segment_ms},
                    punc_model="ct-punc",
                    spk_model="cam++",
                    device=self.device, ncpu=self.ncpu, hub="ms",
                    disable_update=True,
                )
            from modelscope.pipelines import pipeline
            from modelscope.utils.constant import Tasks
            return pipeline(
                task=Tasks.auto_speech_recognition,
                model=self.asr_model, vad_model=self.vad_model,
                punc_model=self.punc_model, spk_model=self.spk_model,
                disable_update=True, disable_progress_bar=True,
                disable_log=True, device=self.device,
            )

        # If the user disabled RAM caching after another project, remove
        # its previous resident model before allocating this new instance.
        if not self.keep_loaded:
            from asr.model_pool import clear_model
            clear_model()
        try:
            log.info("loading FunASR backend=%s on %s (keep_loaded=%s)",
                     self.backend, self.device, self.keep_loaded)
            if self.keep_loaded:
                from asr.model_pool import acquire_model
                key = (self.backend, self.asr_model, self.vad_model,
                       self.punc_model, self.spk_model, self.device,
                       self.ncpu, self.max_vad_segment_ms,
                       self.metrics["cache_dir"])
                self._pipe, self._inference_lock, reused = acquire_model(
                    key, build_model)
                self.metrics["reused_loaded_model"] = reused
            else:
                self._pipe = build_model()
            self.metrics["model_load_seconds"] = round(
                time.perf_counter() - load_started, 3)
            log.info("FunASR model load %.2fs (cache: %s)",
                     self.metrics["model_load_seconds"], self.metrics["cache_dir"])
        except Exception as e:  # noqa: BLE001
            raise ASRError(
                "Không tải được model ASR (lần đầu cần mạng để tải ~1.3GB model).\n"
                f"Cách khắc phục: kiểm tra mạng rồi chạy lại. Chi tiết: {e}") from e

    def transcribe(self, wav_path: str | Path) -> List[Segment]:
        """Transcribe 16kHz mono wav -> raw segments (ms converted to sec).

        Edge case 17: wavs longer than ASR_CHUNK_SEC are cut into 10-minute
        chunks, transcribed one by one, and the segments are re-joined with
        the chunk offset added back.
        """
        self._started_at = time.perf_counter()
        self.metrics["inference_seconds"] = 0.
        self.metrics["boundary_review_count"] = 0
        self.metrics["chunk_count"] = 0
        self.metrics["reused_loaded_model"] = self._pipe is not None
        self.load()
        wav_path = Path(wav_path)
        dur = _wav_duration_sec(wav_path)
        self.metrics["audio_seconds"] = round(dur, 3)
        if dur <= ASR_CHUNK_SEC:
            return self._finalize(self.post_fix(self._transcribe_one(str(wav_path))))
        n = int(math.ceil(dur / ASR_CHUNK_SEC))
        self.metrics["chunk_count"] = n
        # Limit the look-behind/look-ahead on tiny synthetic test chunks.
        extra = min(self.chunk_overlap_sec, ASR_CHUNK_SEC / 4.0)
        log.info("audio dài %.0fs, chia %d chunk ~%d phút để ASR (edge 17)",
                 dur, n, ASR_CHUNK_SEC // 60)
        tmpdir = Path(tempfile.mkdtemp(prefix="vd_asr_"))
        # Chunk speaker IDs are local: never treat spk0 in chunk two as
        # the same person as spk0 in chunk one without full-video evidence.
        chunk_speaker_ids: dict[tuple[int, int], int] = {}
        try:
            segments: List[Segment] = []
            for ci in range(n):
                off = ci * ASR_CHUNK_SEC
                nominal_end = min(dur, off + ASR_CHUNK_SEC)
                # Decode overlapping audio around 10-min boundaries to
                # avoid chopping Chinese syllables and adjacent characters.
                actual_start = max(0., off - extra)
                actual_end = min(dur, nominal_end + extra)
                length = actual_end - actual_start
                chunk = tmpdir / f"chunk_{ci:03d}.wav"
                p = subprocess.run(
                    [_bin.ffmpeg_cmd(), "-y", "-v", "error",
                     "-ss", f"{actual_start:.3f}", "-t", f"{length:.3f}",
                     "-i", str(wav_path), "-c:a", "pcm_s16le", str(chunk)],
                    capture_output=True, text=True)
                if p.returncode != 0 or not chunk.exists():
                    raise ASRError(
                        f"Cắt audio chunk {ci + 1}/{n} thất bại: {p.stderr[:200]}")
                log.info(
                    "ASR chunk %d/%d nominal %.3f-%.3f, decoded %.3f-%.3f",
                    ci + 1, n, off, nominal_end, actual_start, actual_end)
                for s in self._transcribe_one(str(chunk)):
                    s.start += actual_start
                    s.end += actual_start
                    midpoint = (s.start + s.end) / 2.
                    if midpoint < off or midpoint >= nominal_end:
                        # Adjacent chunk owns this utterance's midpoint.
                        # Do not append duplicate overlap material.
                        continue
                    if extra and (ci > 0 and s.start < off + extra or
                                  ci < n - 1 and s.end > nominal_end - extra):
                        s.needs_review = True
                        self.metrics["boundary_review_count"] += 1
                    key = (ci, s.speaker)
                    if key not in chunk_speaker_ids:
                        chunk_speaker_ids[key] = len(chunk_speaker_ids)
                    s.speaker = chunk_speaker_ids[key]
                    if ci > 0:
                        s.needs_review = True
                    segments.append(s)
            return self._finalize(self.post_fix(segments))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def _finalize(self, segments: List[Segment]) -> List[Segment]:
        # Microsecond-scale mock jobs must not round total time to zero
        # while inference time remains positive.
        self.metrics["total_seconds"] = max(
            round(time.perf_counter() - self._started_at, 6),
            self.metrics["inference_seconds"])
        self.metrics["real_time_factor"] = round(
            self.metrics["inference_seconds"] / max(self.metrics["audio_seconds"], .001), 4)
        self.metrics["segment_count"] = len(segments)
        log.info("FunASR profile: %s", self.metrics)
        return segments

    def _transcribe_one(self, wav_path: str) -> List[Segment]:
        """Transcribe a single (short) wav -> raw segments, no chunking."""
        # Shared AutoModel has mutable internal buffers. Serialize inference
        # across jobs using the same in-memory model instance.
        with self._inference_lock:
            started = time.perf_counter()
            try:
                if self.backend == "automodel":
                    res = self._pipe.generate(
                        input=wav_path, batch_size_s=self.batch_size_s,
                        batch_size_threshold_s=max(5, self.batch_size_s // 2))
                else:
                    res = self._pipe(wav_path)
            except Exception as e:  # noqa: BLE001
                raise ASRError(
                    "ASR bị lỗi khi nghe (có thể hết RAM).\n"
                    f"Cách khắc phục: đóng bớt app khác rồi chạy lại. Chi tiết: {e}") from e
            finally:
                self.metrics["inference_seconds"] += time.perf_counter() - started
        if not res or "sentence_info" not in res[0]:
            keys = sorted(res[0].keys()) if res and isinstance(res[0], dict) else []
            raise ASRError(
                "ASR không trả về sentence_info có timestamp để lồng tiếng. "
                "Chưa thể xác minh độ chính xác: " + str(keys)
                + ". Chọn lại backend modelscope hoặc kiểm tra model FunASR.")
        segments: List[Segment] = []
        for i, it in enumerate(res[0]["sentence_info"]):
            text = (it.get("text") or "").strip()
            if not text:
                continue
            spk_raw = it.get("spk", 0)
            try:
                spk = int(str(spk_raw).replace("spk", ""))
            except ValueError:
                spk = 0
            raw_confidence = it.get("confidence")
            # ModelScope often omits calibrated ASR confidence. Do not
            # fabricate 1.0 for unknown speech quality.
            try:
                value = float(raw_confidence) if raw_confidence is not None else .5
                if not math.isfinite(value) or not 0 <= value <= 1:
                    raw_confidence, value = None, .5
            except (TypeError, ValueError):
                raw_confidence, value = None, .5
            segments.append(Segment(
                index=i,
                start=float(it.get("start", 0)) / 1000.0,
                end=float(it.get("end", 0)) / 1000.0,
                speaker=spk, text_src=text, source_lang="zh",
                confidence=value,
                needs_review=raw_confidence is None,
            ))
        log.info("transcribed %d raw segments", len(segments))
        return segments

    @staticmethod
    def post_fix(segments: List[Segment],
                 del_end_punc: bool = False) -> List[Segment]:
        """Conservative cleanup: remove garbage and invalid times;
        preserve overlapping speech and flag it instead of deleting words."""
        kept: List[Segment] = []
        for seg in segments:
            text = (seg.text_src or "").strip()
            if not text or _NON_WORD.match(text):
                log.warning("bỏ câu toàn ký tự rác: %r", text[:60])
                continue
            kept.append(seg)
        # Sweep all overlapping spans, not just adjacent segments. Nested
        # utterances (A spans B and C, but B and C do not overlap) are common
        # when one speaker continues while another interjects.
        active: List[Segment] = []
        for cur in sorted(kept, key=lambda seg: (seg.start, seg.end)):
            active = [prev for prev in active if prev.end > cur.start]
            for prev in active:
                log.warning(
                    "ASR simultaneous/overlapping utterances %d / %d "
                    "(%.3fs); retain BOTH original timestamp ranges",
                    prev.index, cur.index, min(prev.end, cur.end) - cur.start)
                prev.needs_review = True
                cur.needs_review = True
            active.append(cur)
        out: List[Segment] = []
        for seg in kept:
            if seg.end <= seg.start:
                log.warning("bỏ câu end<=start: %r", seg.text_src[:60])
                continue
            if del_end_punc:
                seg.text_src = seg.text_src.strip("。，？！,.?!").strip()
            out.append(seg)
        for new_i, seg in enumerate(out):
            seg.index = new_i
        return out
