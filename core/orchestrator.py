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
from core.logger import setup_job_logger
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
        # last failure message (Wave 2 UI shows this in the error dialog).
        self.last_error: Optional[str] = None

    # -- main entry ---------------------------------------------------------
    def run(self, resume_from: Optional[str] = None) -> str:
        job, proj = self.job, self.job.project
        job.status = RUNNING
        if all(cp.has_step(job.job_dir, s) for s in STEPS):
            self.logger.info("job %s: mọi bước đã có checkpoint -> DONE",
                             job.job_id)
            job.status = DONE
            return DONE
        start_from = resume_from or job.resume_from or self._first_missing_step()
        if proj.overnight and proj.review_stops:
            self.logger.info("chế độ qua đêm: tự TẮT điểm dừng duyệt "
                             "(không treo chờ người giữa đêm)")
        self.logger.info("bắt đầu job %s từ bước '%s' (overnight=%s)",
                         job.job_id, start_from or "fetch", proj.overnight)

        step_idx = STEPS.index(start_from) if start_from in STEPS else 0
        try:
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
                    self.logger.info("tạm dừng theo yêu cầu, tiếp tục từ %s",
                                     STEP_LABEL[step])
                    job.emit_progress("paused", 100.0, "Đã tạm dừng")
                    return PAUSED
                if cp.has_step(job.job_dir, step) and step != start_from:
                    self.logger.info("%s: đã có checkpoint, bỏ qua",
                                     STEP_LABEL[step])
                    continue
                self._run_step(step)
                if (proj.effective_review_stops() and step in REVIEW_AFTER):
                    job.status = REVIEW
                    job.resume_from = STEPS[STEPS.index(step) + 1]
                    pio.save_project(job.job_dir, proj)
                    self.logger.info("dừng ở điểm duyệt sau %s, chờ duyệt tay",
                                     STEP_LABEL[step])
                    return REVIEW
            job.status = DONE
            job.resume_from = None
            self.logger.info("job %s HOÀN THÀNH", job.job_id)
            return DONE
        except Exception as e:  # noqa: BLE001 - logged with traceback, no crash
            job.status = FAILED
            self.last_error = str(e)
            pio.save_project(job.job_dir, proj)
            self.logger.error("job %s THẤT BẠI ở bước '%s': %s\n%s",
                              job.job_id, step, e, traceback.format_exc())
            return FAILED
        finally:
            pio.save_project(job.job_dir, proj)
            job.emit_progress("done", 100.0, job.status)

    def _first_missing_step(self) -> str:
        for step in STEPS:
            if not cp.has_step(self.job.job_dir, step):
                return step
        return "render"

    # -- per-step dispatch ---------------------------------------------------
    def _run_step(self, step: str) -> None:
        job = self.job
        job.emit_progress(step, 0.0, f"{STEP_LABEL[step]} ...")
        t0 = time.time()
        self.logger.info("--- %s ---", STEP_LABEL[step])
        try:
            handler = getattr(self, f"_step_{step}")
            handler()
            cp.mark_done(job.job_dir, job.project, step)
        finally:
            dt = time.time() - t0
            self.timings[step] = dt
            self.logger.info("%s xong trong %.1fs", STEP_LABEL[step], dt)
            job.emit_progress(step, 100.0, f"{STEP_LABEL[step]} xong ({dt:.1f}s)")

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
                "fetch", pct, f"Tải video {pct:.0f}% {spd}"))
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
            mres.check_ram(dur)
        wav = mextract.extract_audio(video, job.stages_dir / "audio.wav",
                                     audio_track=int(job.project.audio_track or 0))
        cp.save_step(job.job_dir, "extract", {"wav_path": str(wav)})

    def _step_asr(self):
        from asr.funasr_adapter import FunASRAdapter
        job = self.job
        s = self.settings
        data = cp.load_step(job.job_dir, "extract") or {}
        wav = data.get("wav_path")
        adapter = FunASRAdapter(asr_model=s.get("asr_model"),
                                vad_model=s.get("vad_model"),
                                punc_model=s.get("punc_model"),
                                spk_model=s.get("spk_model"))
        segments = adapter.transcribe(wav)
        # edge case 5: low ASR confidence -> needs_review
        conf_thr = float(s.get("asr_confidence_low", 0.5))
        for seg in segments:
            if seg.confidence < conf_thr:
                seg.needs_review = True
                self.logger.warning("câu %d confidence thấp (%.2f) -> "
                                    "đánh dấu cần duyệt", seg.index,
                                    seg.confidence)
        pio.save_segments(job.job_dir, "asr", segments)
        n_review = sum(1 for x in segments if x.needs_review)
        self.logger.info("ASR: %d câu, %d loa, %d câu cần duyệt tay",
                         len(segments), len({x.speaker for x in segments}),
                         n_review)

    def _step_gender(self):
        from speaker import gender as mgender
        job = self.job
        segments = pio.load_segments(job.job_dir, "asr") or []
        data = cp.load_step(job.job_dir, "extract") or {}
        speakers = mgender.estimate_genders(
            data.get("wav_path"), segments,
            male_max_hz=float(self.settings.get("pitch_male_max_hz", 160.0)),
            female_min_hz=float(self.settings.get("pitch_female_min_hz", 165.0)))
        # Tôn trọng sửa tay ở màn duyệt #1 (DESIGN): checkpoint "gender" do
        # màn duyệt lưu đã chứa gender user đặt -> giữ lại, không để pitch
        # ghi đè. Chỉ áp dụng khi user đã đặt rõ male/female.
        manual = pio.load_speakers(job.job_dir, "gender") or {}
        for spk_id, mspk in manual.items():
            if mspk.gender in ("male", "female") and spk_id in speakers:
                if speakers[spk_id].gender != mspk.gender:
                    self.logger.info(
                        "giữ giới tính do người dùng sửa tay cho loa %d: %s "
                        "(pitch đoán %s)", spk_id, mspk.gender,
                        speakers[spk_id].gender)
                    speakers[spk_id].gender = mspk.gender
                    speakers[spk_id].confidence = max(
                        speakers[spk_id].confidence, mspk.confidence)
        for seg in segments:
            spk = speakers.get(seg.speaker)
            if spk:
                seg.gender = spk.gender
        pio.save_segments(job.job_dir, "asr", segments)  # persist genders
        pio.save_speakers(job.job_dir, "gender", speakers)

    def _translators(self):
        from translation.nine_router import NineRouterTranslator
        from translation.ollama import OllamaTranslator
        s = self.settings
        providers = []
        order = [self.job.project.translate_provider, "9router", "ollama"]
        seen = set()
        for name in order:
            if name in seen:
                continue
            seen.add(name)
            try:
                if name == "9router":
                    providers.append(NineRouterTranslator(
                        api_key=s.get("nine_router_key", ""),
                        base_url=s.get("nine_router_url",
                                       "https://opencode.ai/zen/v1"),
                        model=s.get("nine_router_model",
                                    "mimo-v2.6-flash-free"),
                        temperature=float(s.get("llm_temperature", 0.2)),
                        batch_size=int(s.get("translate_batch", 20)),
                        proper_nouns=list(s.get("proper_nouns", []))))
                elif name == "ollama":
                    if s.get("ollama_model"):
                        providers.append(OllamaTranslator(
                            base_url=s.get("ollama_url",
                                           "http://localhost:11434"),
                            model=s.get("ollama_model", ""),
                            temperature=float(s.get("llm_temperature", 0.2)),
                            batch_size=int(s.get("translate_batch", 20)),
                            proper_nouns=list(s.get("proper_nouns", []))))
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
                "Cách khắc phục: mở Cài đặt -> nhập API key 9Router "
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
                pio.save_speakers(job.job_dir, "analyze", speakers)
                pio.save_video_metadata(job.job_dir, meta)
                self.logger.info("phân tích quan hệ xong bằng %s", prov.name)
                return
            except Exception as e:  # noqa: BLE001
                last_err = e
                self.logger.warning("analyze bằng %s lỗi: %s", prov.name, e)
        raise RuntimeError(f"Phân tích quan hệ thất bại: {last_err}")

    def _step_translate(self):
        from translation.base import translate_with_fallback
        job = self.job
        segments = pio.load_segments(job.job_dir, "asr") or []
        speakers = pio.load_speakers(job.job_dir, "analyze") \
            or pio.load_speakers(job.job_dir, "gender") or {}
        providers = self._translators()
        # step [4] already analyzed (checkpoint exists) -> do NOT analyze
        # a second time inside translate_with_fallback
        analyze_done = cp.has_step(job.job_dir, "analyze")
        video_metadata = pio.load_video_metadata(job.job_dir) or {}
        segments, used = translate_with_fallback(
            providers, segments, speakers, skip_analyze=analyze_done,
            video_metadata=video_metadata)
        pio.save_segments(job.job_dir, "translate", segments)
        self.logger.info("dịch xong bằng %s: %d câu", used, len(segments))

    def _synthesize_tts(self, tts, segments, tts_dir):
        """TTS with fallback: Edge-TTS first, gTTS (single voice) when Edge
        fails for ALL sentences (DESIGN.md fallback table, edge case 6)."""
        from tts import edge_tts as metts
        from tts import gtts as mgtts
        try:
            return tts.synthesize(segments, tts_dir)
        except metts.TTSError as e:
            self.logger.warning(
                "Edge-TTS lỗi toàn bộ (%s), chuyển sang gTTS (giọng đơn, "
                "không phân biệt nam/nữ)", str(e).split("\n")[0][:160])
            g = mgtts.GTTS()
            return g.synthesize(segments, tts_dir)

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
        rounds = 0
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
                rounds += 1
                if rounds > max_rounds:
                    raise RuntimeError(
                        f"Không tách câu vừa khung giờ sau {max_rounds} lần "
                        f"thử (câu {e.segment.index}).\nCách khắc phục: rút "
                        "ngắn bản dịch câu này ở bước [5] rồi chạy lại.") from e
                self.logger.info("câu %d quá dài (tỉ lệ %.2f) -> tách câu "
                                 "làm %d/%d", e.segment.index, e.ratio,
                                 rounds, max_rounds)
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
                for j, sg in enumerate(segments):
                    sg.index = j
                # re-TTS the two halves, then re-plan
                segments = synthesize_fn(segments)

    def _step_tts(self):
        from tts import edge_tts as metts
        from tts import duration_fit as mfit
        from media import extract as mextract
        job = self.job
        s = self.settings
        segments = pio.load_segments(job.job_dir, "translate") or []
        tts_dir = job.stages_dir / "tts"
        tts = metts.EdgeTTS(
            voice_male=s.get("voice_male"), voice_female=s.get("voice_female"),
            rate=s.get("tts_rate", "+0%"), pitch=s.get("tts_pitch", "+0Hz"),
            concurrency=int(s.get("tts_concurrency", 10)))
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
                     {"dub_track": str(dub_track), "total_sec": total})

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
        mrender.render(fetch_data.get("video_path") or proj.video_in,
                       mix_data["mixed_wav"], srt_path, out_mp4,
                       sub_mode=self.settings.get("sub_mode", proj.sub_mode) or "burn",
                       crf=int(self.settings.get("crf", 20)),
                       font=(self.settings.get("sub_font", "") or "").strip(),
                       font_size=int(self.settings.get("sub_font_size", 0) or 0),
                       font_color=(self.settings.get("sub_font_color", "") or "").strip())
        proj.video_out = str(out_mp4)
        cp.save_step(job.job_dir, "render",
                     {"video_out": str(out_mp4), "srt": str(srt_path)})
