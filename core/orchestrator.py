# VietDub - Vietnamese dubbing for Chinese videos (PySide6 desktop app)
# Copyright (C) 2026 VietDub contributors
# License: GNU General Public License v3.0 (see LICENSE)
"""Orchestrator: runs the 9 pipeline steps for ONE Job, in order.

Rules (from DESIGN.md + follow-ups):
- Overnight mode: review_stops is force-disabled in code (never hangs
  waiting for a human at 3am).
- Core NEVER blocks on user input: no input(), no dialogs. Review stops
  return control with status="review"; the UI resumes by calling run()
  again. Errors follow retry/fallback chains and are logged.
- Real checkpoint after every step -> crash/power-loss resumes from the
  last finished step.
- Every job logs to jobs/<job_id>/run.log; per-step timing is recorded
  (used for the 90-minute extrapolation in Wave 3).
"""
from __future__ import annotations

import logging
import time
import traceback
from pathlib import Path
from typing import Dict, List, Optional

from core import checkpoint as cp
from core.job import CANCELLED, DONE, FAILED, PAUSED, REVIEW, RUNNING, Job
from core.job_store import JobStore
from core.job_recovery import inspect_job
from core.review_state import REVIEW_NEXT, save_pending_review
from core.logger import activate_job_logger, close_job_logger, setup_job_logger
from core.settings import Settings
from project import io as pio
from project.schema import Segment, Speaker

log = logging.getLogger("vietdub.orchestrator")

# (step_name, checkpoint_key, needs_review_after)
STEPS = ["fetch", "extract", "asr", "gender", "analyze", "translate",
         "tts", "mix", "render"]
STEP_LABEL = {
    "fetch": "[0] Lấy video",
    "extract": "[1] Tách audio",
    "asr": "[2] Nghe + tách loa",
    "gender": "[3] Đoán giới tính",
    "analyze": "[4] Phân tích quan hệ",
    "translate": "[5] Dịch",
    "tts": "[6] Lồng tiếng",
    "mix": "[7] Trộn audio",
    "render": "[8] Ghép video",
}
REVIEW_AFTER = {"asr", "translate"}  # only when review_stops and not overnight


class Orchestrator:
    def __init__(self, job: Job, settings: Optional[Settings] = None):
        self.job = job
        self.settings = settings or Settings()
        from media import _bin as mbin
        mbin.configure(self.settings.get("ffmpeg_path"))
        self.logger = setup_job_logger(job.job_id, job.job_dir,
                                       log_cb=job.emit_log)
        self.timings: Dict[str, float] = {}
        self.job_store = JobStore()
        # last failure message (Wave 2 UI shows this in the error dialog).
        self.last_error: Optional[str] = None

    # -- main entry ---------------------------------------------------------
    def run(self, resume_from: Optional[str] = None) -> str:
        job, proj = self.job, self.job.project
        activate_job_logger(job.job_id)
        job.status = RUNNING
        step = resume_from or job.resume_from or "fetch"
        try:
            inspection = inspect_job(self.job_store, job.job_id,
                                     sub_mode=self.settings.get("sub_mode", proj.sub_mode))
            seed_url_identity = (proj.video_source == "url" and not job.force_fetch
                                 and (resume_from or job.resume_from) != "fetch"
                                 and not inspection.damaged and not inspection.source_changed
                                 and not inspection.blocked_reason
                                 and inspection.resume_from != "fetch"
                                 and self._has_step("fetch"))
            if inspection.can_open_review:
                job.status = REVIEW
                job.resume_from = inspection.review_resume_from
                self._save_state(last_stage=inspection.pending_review, last_error="",
                                 seed_fetched_identity=seed_url_identity)
                return REVIEW
            self._save_state(last_error="", seed_fetched_identity=seed_url_identity)
            if not resume_from and not job.resume_from and all(
                    self._has_step(s) for s in STEPS):
                self.logger.info("job %s: mọi bước đã có checkpoint -> DONE",
                                 job.job_id)
                job.status = DONE
                job.resume_from = None
                self._save_state(progress=100.0, last_error="")
                return DONE
            requested = resume_from or job.resume_from
            first_missing = self._first_missing_step()
            start_from = requested or first_missing
            if (requested in STEPS
                    and STEPS.index(first_missing) < STEPS.index(requested)):
                start_from = first_missing
            if proj.overnight and proj.review_stops:
                self.logger.info("chế độ qua đêm: tự TẮT điểm dừng duyệt "
                                 "(không treo chờ người giữa đêm)")
            self.logger.info("bắt đầu job %s từ bước '%s' (overnight=%s)",
                             job.job_id, start_from or "fetch", proj.overnight)
            step_idx = STEPS.index(start_from) if start_from in STEPS else 0
            for step in STEPS[step_idx:]:
                # Wave 2 UI control: pause/cancel take effect BETWEEN steps
                # (each step is atomic and checkpointed). The current step
                # always finishes first; the UI shows "sẽ dừng sau bước
                # hiện tại" so the user is not misled.
                if job.cancel_requested:
                    job.cancel_requested = False
                    job.status = CANCELLED
                    job.resume_from = step
                    pio.save_project(job.job_dir, proj)
                    self._save_state(last_error="")
                    self.logger.info("đã hủy theo yêu cầu, dừng trước %s "
                                     "(checkpoint giữ nguyên, chạy tiếp được)",
                                     STEP_LABEL[step])
                    job.emit_progress("cancelled", 100.0, "Đã hủy")
                    return CANCELLED
                if job.pause_requested:
                    job.pause_requested = False
                    job.status = PAUSED
                    job.resume_from = step
                    pio.save_project(job.job_dir, proj)
                    self._save_state(last_error="")
                    self.logger.info("tạm dừng theo yêu cầu, tiếp tục từ %s",
                                     STEP_LABEL[step])
                    job.emit_progress("paused", 100.0, "Đã tạm dừng")
                    return PAUSED
                if self._has_step(step) and step != start_from:
                    self.logger.info("%s: đã có checkpoint, bỏ qua",
                                     STEP_LABEL[step])
                    continue
                cp.invalidate_from(job.job_dir, proj, step)
                self._run_step(step)
                if (proj.effective_review_stops() and step in REVIEW_AFTER):
                    self.logger.info("dừng ở điểm duyệt sau %s, chờ duyệt tay",
                                     STEP_LABEL[step])
                    return REVIEW
            job.status = DONE
            job.resume_from = None
            self._save_state(progress=100.0, last_error="")
            self.logger.info("job %s HOÀN THÀNH", job.job_id)
            return DONE
        except Exception as e:  # noqa: BLE001 - logged with traceback, no crash
            job.status = FAILED
            # The retry button resumes from this field. Keep it aligned with
            # the step that actually failed, including explicit reruns such
            # as retranslation from the review screen.
            job.resume_from = step
            self.last_error = str(e)
            try:
                pio.save_project(job.job_dir, proj)
            except Exception as save_error:  # noqa: BLE001 - retain the original failure
                self.last_error = f"{self.last_error}; không lưu được project: {save_error}"
            try:
                self._save_state(last_error=self.last_error)
            except Exception as save_error:  # noqa: BLE001 - retain the original failure
                self.last_error = f"{self.last_error}; {save_error}"
            self.logger.error("job %s THẤT BẠI ở bước '%s': %s\n%s",
                              job.job_id, step, e, traceback.format_exc())
            return FAILED
        finally:
            final_save_failed = False
            try:
                pio.save_project(job.job_dir, proj)
            except Exception as save_error:  # noqa: BLE001 - worker must report a result
                final_save_failed = True
                job.status = FAILED
                detail = f"Không thể lưu project: {save_error}"
                self.last_error = f"{self.last_error}; {detail}" if self.last_error else detail
                try:
                    self._save_state(last_error=self.last_error)
                except Exception as state_error:  # noqa: BLE001
                    self.last_error = f"{self.last_error}; {state_error}"
                self.logger.error("job %s: %s", job.job_id, self.last_error)
            job.emit_progress("done", 100.0, job.status)
            close_job_logger(job.job_id)
            if final_save_failed:
                return FAILED

    def _tts_config(self) -> dict:
        """Pin the audio-producing TTS identity, including optional providers.

        The visual-cleanup branch must preserve the TTS checkpoint contract
        when combined with the VieNeu/ZeroTTS branch. Legacy projects that
        predate provider selection continue to be treated as Edge-TTS.
        """
        p = self.job.project
        provider = getattr(p, "tts_provider", "edge")
        config = {
            "version": 1,
            "provider": provider,
            "voice_male": p.voice_male,
            "voice_female": p.voice_female,
        }
        if provider == "vieneu":
            config.update(
                backend=getattr(p, "vieneu_backend", "auto"),
                precision=getattr(p, "vieneu_precision", "fp32"),
                model="v3turbo",
            )
        elif provider == "zerotts":
            config.update(
                model_dir=getattr(p, "zerotts_model_dir", "model/ZeroTTS"),
                speaker_voices=dict(getattr(p, "zerotts_voices", {})),
            )
        elif provider == "edge":
            config.update(rate=p.tts_rate, pitch=p.tts_pitch)
        else:
            raise ValueError(f"Unsupported TTS provider: {provider}")
        return config

    def _visual_opt(self, key, default=None):
        """New jobs use their immutable config snapshot; old jobs keep legacy behavior."""
        options = self.job.project.visual_cleanup_options
        if options:
            return options.get(key, default)
        return self.settings.get(key, default)

    def _visual_cleanup_signature(self):
        """Render checkpoint inputs that must invalidate any stale final MP4."""
        if not self._visual_opt("visual_cleanup_enabled", False):
            return None
        review_file = str(self._visual_opt("visual_cleanup_review_plan", "") or "").strip()
        review_hash = ""
        if review_file:
            import hashlib
            path = Path(review_file)
            # Missing review files invalidate stale output and then fail
            # explicitly in _step_render, rather than returning DONE.
            review_hash = (hashlib.sha256(path.read_bytes()).hexdigest()
                           if path.is_file() else "missing")
        return {
            "enabled": True,
            "backend": str(self._visual_opt("visual_cleanup_backend", "cv")),
            "vsr_root": str(self._visual_opt("visual_vsr_root", "")),
            "vsr_mode": str(self._visual_opt("visual_vsr_mode", "sttn-det")),
            "lama_weight_path": str(self._visual_opt("visual_lama_weight_path", "")),
            "lama_weight_stat": (
                [Path(self._visual_opt("visual_lama_weight_path")).stat().st_size,
                 Path(self._visual_opt("visual_lama_weight_path")).stat().st_mtime_ns]
                if self._visual_opt("visual_lama_weight_path")
                and Path(self._visual_opt("visual_lama_weight_path")).is_file()
                else None),
            "mode": str(self._visual_opt("visual_cleanup_mode", "blur")),
            "interval": float(self._visual_opt("visual_cleanup_interval_sec", 0.65)),
            "min_hits": int(self._visual_opt("visual_cleanup_min_hits", 2)),
            "auto_logo": bool(self._visual_opt("visual_cleanup_auto_logo", False)),
            "review_plan": review_file,
            "review_sha256": review_hash,
        }

    def _has_step(self, step: str) -> bool:
        sub_mode = (self.settings.get("sub_mode", self.job.project.sub_mode)
                    or self.job.project.sub_mode or "burn")
        if not cp.has_step(self.job.job_dir, step, sub_mode=sub_mode):
            return False
        if step == "tts":
            meta = cp.load_step(self.job.job_dir, "tts_meta") or {}
            previous = meta.get("tts_config")
            # Preserve old Edge-TTS jobs without a provider fingerprint.
            if previous is None:
                return getattr(self.job.project, "tts_provider", "edge") == "edge"
            return previous == self._tts_config()
        if step == "render":
            options = self.job.project.visual_cleanup_options or {}
            expected_source = options.get("visual_cleanup_source_sha256")
            if expected_source and options.get("visual_cleanup_enabled"):
                from media.visual_source_identity import file_sha256
                fetch = cp.load_step(self.job.job_dir, "fetch") or {}
                source = fetch.get("video_path") or self.job.project.video_in
                try:
                    if file_sha256(source) != expected_source:
                        return False
                except OSError:
                    return False
            data = cp.load_step(self.job.job_dir, "render") or {}
            # Legacy jobs without this field count as cleanup-disabled.
            # Re-enable/disable/change cleanup => must rerender, never DONE
            # from an incompatible render checkpoint.
            return data.get("visual_cleanup_signature") == self._visual_cleanup_signature()
        return True

    def _first_missing_step(self) -> str:
        for step in STEPS:
            if not self._has_step(step):
                return step
        return "render"

    # -- per-step dispatch ---------------------------------------------------
    def _run_step(self, step: str) -> None:
        job = self.job
        job.emit_progress(step, 0.0, f"{STEP_LABEL[step]} ...")
        t0 = time.time()
        self.logger.info("--- %s ---", STEP_LABEL[step])
        try:
            review_after = job.project.effective_review_stops() and step in REVIEW_AFTER
            if review_after:
                save_pending_review(job.job_dir, step)
            handler = getattr(self, f"_step_{step}")
            handler()
            cp.mark_done(job.job_dir, job.project, step)
            if review_after:
                job.status = REVIEW
                job.resume_from = REVIEW_NEXT[step]
            self._save_state(
                last_stage=step,
                progress=(STEPS.index(step) + 1) * 100.0 / len(STEPS),
                last_error="",
                refresh_source_identity=(step == "fetch"))
        finally:
            dt = time.time() - t0
            self.timings[step] = dt
            self.logger.info("%s xong trong %.1fs", STEP_LABEL[step], dt)
            job.emit_progress(step, 100.0, f"{STEP_LABEL[step]} xong ({dt:.1f}s)")

    def _save_state(self, **changes) -> None:
        try:
            self.job_store.save(self.job, **changes)
        except Exception as exc:
            raise RuntimeError(f"Không thể lưu trạng thái job: {exc}") from exc

    # -- steps ----------------------------------------------------------------
    def _step_fetch(self):
        from media import fetch as mfetch
        job, proj = self.job, self.job.project
        source = proj.video_url if proj.video_source == "url" else proj.video_in
        if not source:
            raise ValueError("Chưa chọn video đầu vào (file hoặc link).")
        path = mfetch.resolve(
            source, job.job_dir,
            progress_cb=lambda pct, spd: job.emit_progress(
                "fetch", pct, f"Tải video {pct:.0f}% {spd}"),
            force_download=job.force_fetch)
        job.force_fetch = False
        proj.video_in = str(path)  # resolved local path for later steps
        cp.save_step(job.job_dir, "fetch", {"video_path": str(path)})

    def _step_extract(self):
        from media import extract as mextract
        from core import resources as mres
        job = self.job
        data = cp.load_step(job.job_dir, "fetch") or {}
        video = data.get("video_path") or job.project.video_in
        try:
            dur = mextract.duration_sec(video)
        except Exception:  # noqa: BLE001 - best effort, ASR still guards itself
            dur = 0.0
        if dur > 0:
            # edge 17: estimate peak RAM before the heavy steps start
            mres.check_ram(dur, self.settings.get("asr_backend", "whisper"))
        wav = mextract.extract_audio(video, job.stages_dir / "audio.wav",
                                     audio_track=int(job.project.audio_track or 0))
        cp.save_step(job.job_dir, "extract", {"wav_path": str(wav)})

    def _step_asr(self):
        """Select ASR by spoken language, never by video filename or captions."""
        import os
        from project import io as pio
        from asr.source_language import (choose_language,
                                         detect_source_language)
        from asr.engine_router import select_asr_engine

        job, settings = self.job, self.settings
        source = cp.load_step(job.job_dir, "extract") or {}
        wav = source.get("wav_path")
        requested_lang = job.project.src_lang or "auto"
        preferred_engine = settings.get("asr_engine", "auto") or "auto"

        if preferred_engine == "auto" and requested_lang == "auto":
            # Inexpensive multilingual language probe BEFORE the heavy ASR.
            # Run at several times, avoiding assumptions from opening music.
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise RuntimeError(
                    "Thiếu faster-whisper để tự động nhận diện ngôn ngữ. "
                    "Cài requirements-asr-hybrid.txt hoặc chọn ngôn ngữ "
                    "nguồn và ASR thủ công.") from exc
            probe = WhisperModel(
                settings.get("language_detection_model", "tiny"),
                device="cpu", compute_type="int8")
            language = detect_source_language(wav, probe)
            del probe
        elif requested_lang != "auto":
            language = choose_language([], requested=requested_lang)
        elif preferred_engine == "funasr":
            raise ValueError(
                "Muốn ép FunASR phải chọn ngôn ngữ video = Tiếng Trung. "
                "Để tự động chọn engine, đặt ASR = Tự động.")
        else:
            # Forced Whisper with auto-language lets its adapter probe the
            # audio; no guess that a movie with Hanzi subtitles speaks zh.
            language = choose_language([], requested="auto")

        route = select_asr_engine(
            language, preferred_engine,
            chinese_min_confidence=float(
                settings.get("chinese_asr_min_confidence", .70)))
        cp.save_step(job.job_dir, "asr_route", route.to_dict())
        self.logger.info(
            "Định tuyến ASR: %s | ngôn ngữ=%s | lý do=%s",
            route.engine, route.language, route.reason)

        if route.engine == "qwen3_asr":
            from asr.qwen3_adapter import Qwen3ASRAdapter
            adapter = Qwen3ASRAdapter(
                model=settings.get("qwen_asr_model", "Qwen/Qwen3-ASR-0.6B"),
                aligner=settings.get("qwen_asr_aligner",
                                     "Qwen/Qwen3-ForcedAligner-0.6B"),
                device=settings.get("qwen_asr_device", "auto"),
                language=requested_lang)
            segments = adapter.transcribe(wav)
            quality = dict(adapter.last_evidence)
            language_evidence = language.to_dict()
            job.project.detected_src_lang = quality.get("language_detected", "und")
            job.project.language_review_required = True
            self.logger.info("Qwen3-ASR: %d đoạn thoại (cần duyệt)",len(segments))
        elif route.engine == "whisper_pyannote":
            from asr.whisper_pyannote_adapter import WhisperPyannoteAdapter
            adapter = WhisperPyannoteAdapter(
                model=settings.get("whisper_model", "large-v3-turbo"),
                token=settings.get("hf_token", ""),
                device=settings.get("asr_device", "auto"),
                forced_alignment=bool(
                    settings.get("whisper_forced_alignment", True)),
                source_language=requested_lang,
                initial_decision=(language if language.mode != "unresolved"
                                  else None))
            segments = adapter.transcribe(wav)
            quality = adapter.last_evidence
            language_evidence = quality.get("language_detection",
                                            language.to_dict())
            job.project.detected_src_lang = quality.get(
                "language_detected", language.primary)
            job.project.language_review_required = (
                route.language_review_required or
                bool(quality.get("language_review_required")))
        else:
            from asr.funasr_adapter import FunASRAdapter
            from asr.chinese_quality import (qa_chinese_segments,
                                             reconcile_pyannote_speakers)
            adapter = FunASRAdapter(
                asr_model=settings.get("asr_model"),
                vad_model=settings.get("vad_model"),
                punc_model=settings.get("punc_model"),
                spk_model=settings.get("spk_model"),
                device=("cuda" if settings.get("asr_device") == "cuda"
                        else "cpu"),
                backend=settings.get("funasr_backend", "modelscope"),
                ncpu=int(settings.get("funasr_cpu_threads", 4)),
                keep_loaded=bool(settings.get("funasr_keep_loaded", True)),
                batch_size_s=int(settings.get("funasr_batch_size_s", 60)),
                max_vad_segment_ms=int(
                    settings.get("funasr_max_vad_segment_ms", 15000)),
                chunk_overlap_sec=float(settings.get("funasr_chunk_overlap_sec", 1.5)))
            segments = adapter.transcribe(wav)
            self.logger.info("FunASR profiling: %s", adapter.metrics)
            quality = {
                "performance": dict(adapter.metrics),
                "source": "chinese_funasr",
                "qa_status": "UNAPPROVED",
                "human_verified": False,
                "speaker_diarization_executed": False,
                "speaker_validation_warning": None,
                "forced_alignment_executed": False,
                "segments": [seg.to_dict() for seg in segments]}
            quality["chinese_qa"] = qa_chinese_segments(segments)
            job.project.detected_src_lang = "zh"
            job.project.language_review_required = bool(
                route.language_review_required)
            language_evidence = language.to_dict()

            # FunASR's CAM++ speaker labels are chunk-local. Use one
            # independent pyannote pass over the entire audio to reconcile
            # them if a valid token is available. No fake global matches.
            token = os.getenv("HF_TOKEN") or settings.get("hf_token", "")
            if token:
                try:
                    from pyannote.audio import Pipeline
                    from asr.whisper_pyannote_adapter import annotation_windows
                    import torch
                    pipe = Pipeline.from_pretrained(
                        "pyannote/speaker-diarization-community-1",
                        token=token)
                    if (settings.get("asr_device") == "cuda" and
                            torch.cuda.is_available()):
                        pipe.to(torch.device("cuda"))
                    diarized = pipe(str(wav))
                    exclusive = annotation_windows(
                        diarized.exclusive_speaker_diarization)
                    if not exclusive:
                        raise RuntimeError("pyannote returned no speech turns")
                    regular = annotation_windows(
                        diarized.speaker_diarization)
                    quality["speaker_qa"] = reconcile_pyannote_speakers(
                        segments, exclusive)
                    quality["diarization_exclusive"] = exclusive
                    quality["diarization_regular"] = regular
                    quality["speaker_diarization_executed"] = True
                except Exception as exc:
                    quality["speaker_validation_warning"] = (
                        f"{type(exc).__name__}: {str(exc)[:260]}")
                    self.logger.warning(
                        "Không thể đối chiếu giọng FunASR trên toàn video: %s",
                        exc)
            else:
                quality["speaker_validation_warning"] = (
                    "No HF_TOKEN: speaker IDs after 10-minute chunks "
                    "are not globally reconciled.")

            if settings.get("whisper_forced_alignment", True):
                try:
                    from asr.whisper_align import forced_align
                    raw = [{"id": seg.index, "start": seg.start,
                            "end": seg.end, "text": seg.text_src,
                            "language": "zh"} for seg in segments]
                    aligned, statistics = forced_align(raw, wav)
                    quality["alignment"] = statistics
                    for seg, part in zip(segments, aligned):
                        words = part.get("words") or []
                        if part.get("alignment_status") == "whisperx_aligned" and words:
                            start, end = float(words[0]["start"]), float(words[-1]["end"])
                            if (end > start and abs(start - seg.start) < 2.0 and
                                    abs(end - seg.end) < 2.0):
                                seg.start, seg.end = start, end
                            else:
                                seg.needs_review = True
                        else:
                            seg.needs_review = True
                    quality["forced_alignment_executed"] = bool(
                        statistics.get("aligned", 0))
                except Exception as exc:
                    quality["forced_alignment_warning"] = (
                        f"{type(exc).__name__}: {str(exc)[:260]}")
                    self.logger.warning("Không thể forced-align tiếng Trung: %s", exc)
                    for seg in segments:
                        seg.needs_review = True

            if (settings.get("voice_anchor_review", True) and
                    quality.get("speaker_diarization_executed")):
                try:
                    from speaker.voice_anchors import export_review
                    quality["word_evidence"] = [
                        {"start": seg.start, "end": seg.end,
                         "word": seg.text_src} for seg in segments]
                    quality["segments"] = [seg.to_dict() for seg in segments]
                    anchor_path = export_review(
                        quality, wav, job.stages_dir / "voice_anchor_review")
                    self.logger.info("Mẫu giọng tiếng Trung cần duyệt: %s",
                                     anchor_path)
                except Exception as exc:
                    self.logger.warning("Không xuất được mẫu giọng: %s", exc)

            quality["segments"] = [seg.to_dict() for seg in segments]
            quality["qa_status"] = "UNAPPROVED"

        # Persist evidence and project language independently of ASR backend.
        if route.engine == "whisper_pyannote" and settings.get(
                "voice_anchor_review", True):
            try:
                from speaker.voice_anchors import export_review
                anchor_path = export_review(
                    quality, wav, job.stages_dir / "voice_anchor_review")
                self.logger.info("Mẫu giọng cần duyệt: %s", anchor_path)
            except Exception as exc:
                self.logger.warning("Không xuất được mẫu giọng: %s", exc)

        cp.save_step(job.job_dir, "source_language", language_evidence)
        cp.save_step(job.job_dir, "asr_quality", quality)
        pio.save_project(job.job_dir, job.project)
        for seg in segments:
            if (seg.confidence <
                    float(settings.get("asr_confidence_low", .5))):
                seg.needs_review = True
            if job.project.language_review_required:
                seg.needs_review = True
        pio.save_segments(job.job_dir, "asr", segments)
        self.logger.info(
            "ASR hoàn tất: %s; %d câu; %d speaker cluster; %d cần QA; "
            "language_review=%s",
            route.engine, len(segments),
            len({seg.speaker for seg in segments}),
            sum(seg.needs_review for seg in segments),
            job.project.language_review_required)

    def _step_gender(self):
        from speaker import gender as mgender
        job = self.job
        segments = pio.load_segments(job.job_dir, "asr") or []
        data = cp.load_step(job.job_dir, "extract") or {}
        speakers = mgender.estimate_genders(
            data.get("wav_path"), segments,
            male_max_hz=float(self.settings.get("pitch_male_max_hz", 160.0)),
            female_min_hz=float(self.settings.get("pitch_female_min_hz", 165.0)))
        # Merge the main branch source-review semantics with the multilingual
        # character-identity review: keep only active speakers, never resurrect
        # stale labels from a different transcript, and preserve explicit edits.
        manual = pio.load_speakers(job.job_dir, "source_review")
        if manual is None:
            manual = pio.load_speakers(job.job_dir, "gender") or {}
        active = {seg.speaker for seg in segments}
        manually_labeled = set()
        for spk_id, mspk in manual.items():
            if spk_id not in active:
                continue
            if (mspk.gender in ("male", "female")
                    or (mspk.identity_verified and mspk.character_name)):
                if spk_id not in speakers:
                    speakers[spk_id] = Speaker.from_dict(mspk.to_dict())
            estimated = speakers.get(spk_id)
            if estimated is None:
                continue
            if mspk.identity_verified and mspk.character_name:
                estimated.character_name = mspk.character_name
                estimated.identity_verified = True
            if mspk.gender in ("male", "female"):
                manually_labeled.add(spk_id)
                if estimated.gender != mspk.gender:
                    self.logger.info(
                        "giữ giới tính do người dùng sửa tay cho loa %d: %s "
                        "(pitch đoán %s)", spk_id, mspk.gender, estimated.gender)
                    estimated.gender = mspk.gender
                estimated.confidence = max(
                    estimated.confidence, mspk.confidence)
        threshold = float(self.settings.get("pitch_confidence_low", .7))
        for seg in segments:
            spk = speakers.get(seg.speaker)
            if spk:
                seg.gender = spk.gender
                if (seg.speaker not in manually_labeled
                        and spk.confidence < threshold):
                    seg.needs_review = True
        pio.save_segments(job.job_dir, "asr", segments)  # persist genders
        pio.save_speakers(job.job_dir, "gender", speakers)

    def _translators(self):
        from translation.openai_api import OpenAITranslator
        from translation.nine_router import NineRouterTranslator
        from translation.ollama import OllamaTranslator
        s = self.settings
        providers = []
        configured_names = s.get("proper_nouns", []) or []
        project_names = self.job.project.proper_nouns or []
        if isinstance(configured_names, str):
            configured_names = [configured_names]
        if isinstance(project_names, str):
            project_names = [project_names]
        proper_nouns = list(dict.fromkeys(
            str(name).strip()
            for name in [*configured_names, *project_names]
            if name is not None and str(name).strip()))
        order = [self.job.project.translate_provider, "openai", "9router",
                 "ollama"]
        seen = set()
        for name in order:
            if name in seen:
                continue
            seen.add(name)
            try:
                if name == "9router":
                    if s.get("require_nine_router_key", False) and not s.get("nine_router_key"):
                        self.logger.warning("9Router key missing; skip unstable unauthenticated endpoint")
                        continue
                    providers.append(NineRouterTranslator(
                        api_key=s.get("nine_router_key", ""),
                        base_url=s.get("nine_router_url",
                                       "https://opencode.ai/zen/v1"),
                        model=s.get("nine_router_model",
                                    "mimo-v2.6-flash-free"),
                        temperature=float(s.get("llm_temperature", 0.2)),
                        batch_size=int(s.get("translate_batch", 20)),
                        proper_nouns=list(s.get("proper_nouns", [])),
                        timeout=45, max_retries=1))
                elif name == "ollama":
                    if s.get("ollama_model"):
                        providers.append(OllamaTranslator(
                            base_url=s.get("ollama_url",
                                           "http://localhost:11434"),
                            model=s.get("ollama_model", ""),
                            temperature=float(s.get("llm_temperature", 0.2)),
                            batch_size=int(s.get("translate_batch", 20)),
                            proper_nouns=proper_nouns))
            except Exception as e:  # noqa: BLE001 - misconfigured provider skipped
                self.logger.warning("bỏ qua provider %s: %s", name, e)
        return providers

    def _step_analyze(self):
        job = self.job
        segments = pio.load_segments(job.job_dir, "asr") or []
        speakers = pio.load_speakers(job.job_dir, "gender") or {}
        providers = self._translators()
        if not providers:
            raise ValueError(
                "Chưa cấu hình nguồn dịch nào.\n"
                "Cách khắc phục: mở Cài đặt -> nhập API key OpenAI/9Router "
                "hoặc cấu hình Ollama.")
        # analyze only; translation happens in _step_translate
        last_err = None
        for prov in providers:
            try:
                speakers = prov.analyze(segments, speakers)
                # analyze() also filled per-line audiences + ran the video
                # metadata pass (stored on the provider); persist both
                pio.save_segments(job.job_dir, "asr", segments)
                meta = getattr(prov, "last_video_metadata", None) or {}
                if not meta:
                    try:
                        meta = prov.analyze_video_metadata(segments, speakers)
                    except Exception as me:  # noqa: BLE001 - metadata là phụ,
                        # không được làm hỏng bước analyze chính
                        self.logger.warning("bỏ qua metadata video: %s", me)
                        meta = {"genre": "other", "style": "other",
                                "setting": "other", "tone_notes": ""}
                manual = pio.load_speakers(job.job_dir, "gender") or {}
                for speaker_id, confirmed in manual.items():
                    if (confirmed.identity_verified and confirmed.character_name
                            and speaker_id in speakers):
                        speakers[speaker_id].character_name = confirmed.character_name
                        speakers[speaker_id].identity_verified = True
                pio.save_speakers(job.job_dir, "analyze", speakers)
                meta = {**meta,
                        "source_language": job.project.detected_src_lang,
                        "source_language_requested": job.project.src_lang,
                        "language_review_required": job.project.language_review_required}
                pio.save_video_metadata(job.job_dir, meta)
                self.logger.info("phân tích quan hệ xong bằng %s", prov.name)
                return
            except Exception as e:  # noqa: BLE001
                last_err = e
                self.logger.warning("analyze bằng %s lỗi: %s", prov.name, e)
        self.logger.warning("LLM analyze unavailable (%s); using neutral pronouns", last_err)
        for speaker in speakers.values():
            if not speaker.relations:
                speaker.relations = [{"audience": "audience", "pronoun_i": "tôi",
                                      "pronoun_you": "bạn", "is_default": True}]
                speaker.sync_default_pronouns()
        pio.save_speakers(job.job_dir, "analyze", speakers)
        pio.save_video_metadata(job.job_dir, {"genre": "other", "style": "other",
            "setting": "other", "tone_notes": "Fallback: neutral pronouns; review required",
            "source_language": job.project.detected_src_lang,
            "language_review_required": job.project.language_review_required})

    def _step_translate(self):
        from translation.base import translate_with_fallback
        job = self.job
        segments = pio.load_segments(job.job_dir, "asr") or []
        speakers = pio.load_speakers(job.job_dir, "analyze") \
            or pio.load_speakers(job.job_dir, "gender") or {}
        providers = self._translators()
        # step [4] already analyzed (checkpoint exists) -> do NOT analyze
        # a second time inside translate_with_fallback
        analyze_done = self._has_step("analyze")
        video_metadata = pio.load_video_metadata(job.job_dir) or {}
        video_metadata["source_language"] = job.project.detected_src_lang
        video_metadata["language_review_required"] = job.project.language_review_required
        segments, used = translate_with_fallback(
            providers, segments, speakers, skip_analyze=analyze_done,
            video_metadata=video_metadata)
        # One generic semantic comparison pass via the same configured
        # provider. Failed LLM QA is marked unresolved, never auto-approved.
        if self.settings.get("translation_semantic_review", True):
            from translation.quality import review_with_llm
            import json
            provider = next((p for p in providers if p.name == used), None)
            if provider is not None:
                qa=review_with_llm(
                    segments,provider,video_metadata=video_metadata,
                    batch_size=int(self.settings.get("translation_review_batch",10)))
            else:
                for seg in segments:
                    seg.needs_review = True
                qa={"status":"REVIEW_UNAVAILABLE",
                    "reason":"Translation used provider without LLM reviewer",
                    "human_approved":False}
            (job.stages_dir/"translate_qa.json").write_text(
                json.dumps(qa,ensure_ascii=False,indent=2),encoding="utf-8")
            self.logger.info("semantic QA: %s, %s lines flagged",
                             qa["status"],qa.get("flagged_lines","unknown"))
        pio.save_segments(job.job_dir, "translate", segments)
        self.logger.info("dịch xong bằng %s: %d câu", used, len(segments))

    def _synthesize_tts(self, tts, segments, tts_dir):
        """Fail closed on missing speech or provider failures; never hide errors."""
        voiced = tts.synthesize(segments, tts_dir)
        for seg in voiced:
            if not seg.audio_vi or not Path(seg.audio_vi).is_file():
                raise RuntimeError(
                    f"Câu {seg.index} không có file giọng đọc TTS; "
                    "không được thay âm thanh lỗi bằng khoảng lặng hoặc "
                    "tự đổi voice provider. Hãy chạy lại bước TTS."
                )
        return voiced

    def _fit_and_track(self, segments, tts_dir, synthesize_fn):
        """Split-and-retry loop for too-long sentences (edge case 1).

        Rewritten as a while loop so plan() is ALWAYS re-run after the
        last split - the old for/else raised even when the final split had
        already fixed the problem (off-by-one). Sentences that cannot be
        split get max squeeze + light overflow (edge 2 treatment) instead
        of killing the job.

        Returns (segments, decisions).
        """
        from tts import duration_fit as mfit
        s = self.settings
        max_rounds = 3
        # Count split depth per sentence lineage. A long film can contain
        # many independent long lines; one line must not consume another's
        # retry budget.
        split_depth = {id(seg): 0 for seg in segments}
        overflow_ids = set()
        while True:
            try:
                decisions = mfit.plan(
                    segments,
                    atempo_min=float(s.get("atempo_min", 0.8)),
                    atempo_max=float(s.get("atempo_max", 1.25)),
                    out_dir=tts_dir,
                    force_overflow=overflow_ids)
                return segments, decisions
            except mfit.TooLongError as e:
                depth = split_depth.get(id(e.segment), 0)
                if depth >= max_rounds:
                    raise RuntimeError(
                        f"Không tách câu vừa khung giờ sau {max_rounds} lần "
                        f"thử (câu {e.segment.index}).\nCách khắc phục: rút "
                        "ngắn bản dịch câu này ở bước [5] rồi chạy lại.") from e
                self.logger.info("câu %d quá dài (tỉ lệ %.2f) -> tách câu "
                                 "làm %d/%d", e.segment.index, e.ratio,
                                 depth + 1, max_rounds)
                try:
                    a, b = mfit.split_segment(e.segment)
                except ValueError:
                    # unsplittable -> max squeeze + overflow, warn (edge 2)
                    self.logger.warning(
                        "câu %d không tách được, nén tối đa và cho tràn nhẹ "
                        "quá slot", e.segment.index)
                    overflow_ids.add(id(e.segment))
                    continue
                idx = segments.index(e.segment)
                segments[idx:idx + 1] = [a, b]
                split_depth.pop(id(e.segment), None)
                split_depth[id(a)] = depth + 1
                split_depth[id(b)] = depth + 1
                for j, sg in enumerate(segments):
                    sg.index = j
                # re-TTS the two halves, then re-plan
                segments = synthesize_fn(segments)

    def _step_tts(self):
        from tts import duration_fit as mfit
        from tts.provider import create_tts
        from media import extract as mextract
        from core.release_quality import assert_dub_ready
        job = self.job
        s = self.settings
        segments = pio.load_segments(job.job_dir, "translate") or []
        # Runs AFTER any manual translation review and BEFORE paid/remote TTS.
        # Overnight mode must not silently export incomplete Chinese lines.
        assert_dub_ready(segments)
        tts_dir = job.stages_dir / "tts"
        # Pin the provider/voices on each project (including resumes), not
        # whichever global choice the user made for a different job later.
        tts = create_tts(
            s, provider=job.project.tts_provider,
            voice_male=job.project.voice_male,
            voice_female=job.project.voice_female,
            vieneu_backend=job.project.vieneu_backend,
            vieneu_precision=job.project.vieneu_precision,
            zerotts_model_dir=job.project.zerotts_model_dir,
            zerotts_voices=dict(job.project.zerotts_voices),
            rate=job.project.tts_rate,
            pitch=job.project.tts_pitch)
        segments = self._synthesize_tts(tts, segments, tts_dir)
        segments, decisions = self._fit_and_track(
            segments, tts_dir,
            lambda segs: self._synthesize_tts(tts, segs, tts_dir))
        mfit.apply_plan(decisions)
        extract_data = cp.load_step(job.job_dir, "extract") or {}
        wav_path = extract_data.get("wav_path", "")
        total = 0.0
        if wav_path:
            try:
                total = mextract.duration_sec(wav_path)
            except Exception:  # noqa: BLE001 - fall back to segment end
                total = 0.0
        if not total:
            total = max((sg.end for sg in segments), default=0.0)
        dub_track = mfit.build_track(segments, tts_dir / "dub_track.wav", total)
        pio.save_segments(job.job_dir, "tts", segments)
        cp.save_step(job.job_dir, "tts_meta",
                     {"dub_track": str(dub_track), "total_sec": total,
                      "tts_config": self._tts_config()})

    def _step_mix(self):
        from media import mix as mmix
        job = self.job
        meta = cp.load_step(job.job_dir, "tts_meta") or {}
        orig = (cp.load_step(job.job_dir, "extract") or {}).get("wav_path", "")
        out = mmix.mix(meta["dub_track"], orig, job.stages_dir / "mixed.wav",
                       dub_volume=float(self.settings.get("dub_volume", 1.0)),
                       orig_volume=float(self.settings.get("orig_volume", 0.15)))
        cp.save_step(job.job_dir, "mix", {"mixed_wav": str(out)})

    def _step_render(self):
        from media import render as mrender
        from media import subs as msubs
        job, proj = self.job, self.job.project
        mix_data = cp.load_step(job.job_dir, "mix") or {}
        fetch_data = cp.load_step(job.job_dir, "fetch") or {}
        segments = pio.load_segments(job.job_dir, "tts") \
            or pio.load_segments(job.job_dir, "translate") or []
        srt_path = msubs.write_srt(segments, job.stages_dir / "subs.vi.srt")
        out_name = Path(proj.video_in).stem + "_vidub.mp4"
        out_mp4 = Path(proj.video_out or str(job.job_dir / out_name))
        sub_mode = (self.settings.get("sub_mode", proj.sub_mode)
                    or proj.sub_mode or "burn")
        video_for_render = fetch_data.get("video_path") or proj.video_in
        if self._visual_opt("visual_cleanup_enabled", False):
            expected_source = (proj.visual_cleanup_options or {}).get(
                "visual_cleanup_source_sha256")
            if expected_source:
                from media.visual_source_identity import file_sha256
                if file_sha256(video_for_render) != expected_source:
                    raise RuntimeError(
                        "Source video changed after job creation; "
                        "review the video and masks before starting a new job")
            # Optional step inside render keeps existing checkpoint order stable.
            # Fail explicitly when OCR/runtime is missing; never silently export
            # uncleaned video after the user asked for cleanup.
            from media import visual_cleanup as vclean
            from media import _bin as mbin
            backend = str(self._visual_opt("visual_cleanup_backend", "cv"))
            visual_plan = job.stages_dir / "visual_regions.json"
            reviewed = str(self._visual_opt("visual_cleanup_review_plan", "") or "").strip()
            plan = None
            if reviewed:
                import json
                review_path = Path(reviewed)
                if not review_path.is_file():
                    raise FileNotFoundError(f"Không tìm thấy plan đã duyệt: {review_path}")
                raw_plan = review_path.read_bytes()
                expected_digest = (proj.visual_cleanup_options or {}).get(
                    "visual_cleanup_review_sha256")
                if expected_digest is not None:
                    import hashlib
                    actual_digest = hashlib.sha256(raw_plan).hexdigest()
                    if actual_digest != expected_digest:
                        raise RuntimeError(
                            "Reviewed cleanup plan changed after job creation; "
                            "re-approve the masks and create a new job")
                plan = json.loads(raw_plan.decode("utf-8"))
            if backend == "vsr":
                from media.visual_neural import run_vsr
                mode = str(self._visual_opt("visual_vsr_mode", "sttn-det"))
                root = str(self._visual_opt("visual_vsr_root", "") or "")
                reviewed_windows = [r for r in (plan or {}).get("regions", [])
                                    if r.get("source")=="neural-window"]
                if reviewed_windows:
                    from media.visual_neural_window import run_windowed_vsr
                    video_for_render = run_windowed_vsr(
                        root, video_for_render, job.stages_dir / "visual_clean.mp4",
                        regions=reviewed_windows, mode=mode,
                        ffmpeg=mbin.ffmpeg_cmd())
                else:
                    boxes = [r["box"] for r in (plan or {}).get("regions", [])
                             if r.get("kind") in ("subtitle", "text") and "box" in r]
                    video_for_render = run_vsr(
                        root, video_for_render, job.stages_dir / "visual_clean.mp4",
                        mode=mode, areas=boxes)
                boxes = [r.get("box") for r in (plan or {}).get("regions", [])
                         if r.get("box")]
                # External model does its own OCR detection. Do not present
                # this metadata as though it were PaddleOCR tracking boxes.
                import json
                visual_plan.write_text(json.dumps({
                    "backend": "vsr", "model": mode,
                    "source": str(Path(fetch_data.get("video_path") or proj.video_in).resolve()),
                    "reviewed_areas":boxes,"reviewed_windows":reviewed_windows,
                    "note":"External open-source model; validate the rendered result visually"},
                    ensure_ascii=False,indent=2),encoding="utf-8")
            elif backend == "lama-cpu":
                from media.visual_lama_cpu import render_lama_cpu
                if not plan:
                    raise ValueError("LaMa CPU requires reviewed neural-window regions JSON")
                windows = [r for r in plan.get("regions",[])
                           if r.get("source")=="neural-window"]
                if not windows:
                    raise ValueError("LaMa CPU plan has no approved neural-window regions")
                video_for_render = render_lama_cpu(
                    video_for_render,job.stages_dir/"visual_clean.mp4",
                    model_path=str(self._visual_opt("visual_lama_weight_path","")),
                    regions=windows,ffmpeg=mbin.ffmpeg_cmd())
                import json
                visual_plan.write_text(
                    json.dumps(plan,ensure_ascii=False,indent=2),encoding="utf-8")
            elif backend == "hybrid":
                from media.visual_hybrid import render_reviewed_hybrid
                if not plan:
                    raise ValueError("Hybrid cleanup requires a reviewed JSON plan")
                video_for_render = render_reviewed_hybrid(
                    video_for_render, job.stages_dir / "visual_clean.mp4",
                    plan, model_path=str(self._visual_opt("visual_lama_weight_path", "")),
                    ffmpeg=mbin.ffmpeg_cmd())
                import json
                visual_plan.write_text(
                    json.dumps(plan,ensure_ascii=False,indent=2),encoding="utf-8")
                from media.visual_acceptance import write_audit
                qa = write_audit(
                    job.stages_dir / "visual_acceptance.json",
                    fetch_data.get("video_path") or proj.video_in,
                    video_for_render, plan,
                    required_subtitle_times=plan.get("required_subtitle_times", []))
                if not qa["pass_structural_checks"]:
                    raise RuntimeError("Hybrid cleanup failed structural acceptance: "+
                                       "; ".join(qa["issues"]))
            elif backend == "cv":
                config = vclean.Config(
                    mode=str(self._visual_opt("visual_cleanup_mode", "blur")),
                    sample_sec=float(self._visual_opt("visual_cleanup_interval_sec", 0.65)),
                    min_hits=int(self._visual_opt("visual_cleanup_min_hits", 2)),
                    auto_logo=bool(self._visual_opt("visual_cleanup_auto_logo", False)))
                engine = vclean.VisualCleanup(config)
                if reviewed:
                    if not any(r.get("source") in (
                            "user", "temporal-clean-plate", "exemplar-patch",
                            "flat-strip-repaint") for r in plan.get("regions", [])):
                        raise ValueError("Plan đã duyệt phải có vùng user hoặc vùng clean-plate")
                    video_for_render = engine.render(
                        video_for_render, job.stages_dir / "visual_clean.mp4",
                        plan, ffmpeg=mbin.ffmpeg_cmd())
                    visual_plan.write_text(
                        json.dumps(plan,ensure_ascii=False,indent=2),encoding="utf-8")
                    from media.visual_acceptance import write_audit
                    qa = write_audit(
                        job.stages_dir / "visual_acceptance.json",
                        fetch_data.get("video_path") or proj.video_in,
                        video_for_render, plan,
                        required_subtitle_times=plan.get("required_subtitle_times", []))
                    if not qa["pass_structural_checks"]:
                        raise RuntimeError("Video xử lý chưa đạt kiểm định: "+
                                           "; ".join(qa["issues"]))
                else:
                    video_for_render = engine.process(
                        video_for_render, job.stages_dir / "visual_clean.mp4",
                        plan_path=visual_plan, ffmpeg=mbin.ffmpeg_cmd())
            else:
                raise ValueError(f"Visual cleanup backend không hợp lệ: {backend}")
            if plan and plan.get("ocr_qa_samples"):
                from media.visual_ocr_acceptance import audit_rendered_captions
                qa = audit_rendered_captions(
                    fetch_data.get("video_path") or proj.video_in,
                    video_for_render,
                    plan["ocr_qa_samples"],
                    lang=plan.get("ocr_qa_lang","chi_sim+eng"))
                import json
                (job.stages_dir / "visual_ocr_acceptance.json").write_text(
                    json.dumps(qa,ensure_ascii=False,indent=2),encoding="utf-8")
                if qa["verdict"] != "no_readable_cjk":
                    raise RuntimeError(
                        "Đầu ra chưa đạt kiểm tra phụ đề OCR: "+
                        qa["verdict"]+
                        "; xem visual_ocr_acceptance.json")
            self.logger.info("Visual cleanup output: %s; review plan: %s",
                             video_for_render, visual_plan)
        rendered = mrender.render(
            video_for_render,
            mix_data["mixed_wav"], srt_path, out_mp4,
            sub_mode=sub_mode,
            crf=int(self.settings.get("crf", 20)),
            font=(self.settings.get("sub_font", "") or "").strip(),
            font_size=int(self.settings.get("sub_font_size", 0) or 0),
            font_color=(self.settings.get("sub_font_color", "") or "").strip())
        proj.video_out = str(rendered)
        render_data = {"video_out": str(rendered), "srt": str(srt_path),
                       "visual_cleanup_signature": self._visual_cleanup_signature()}
        if sub_mode == "srt":
            render_data["srt_out"] = str(rendered.with_suffix(".srt"))
        cp.save_step(job.job_dir, "render", render_data)
