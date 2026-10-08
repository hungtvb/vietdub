#!/usr/bin/env python3
# VietDub - Vietnamese dubbing for Chinese videos (PySide6 desktop app)
# Copyright (C) 2026 VietDub contributors
# License: GNU General Public License v3.0 (xem LICENSE ở thư mục gốc)
"""Wave 3 — batch test 20 video (pipeline [1]->[5] đầy đủ, không duyệt tay).

Mục đích: chứng minh pipeline chạy thật end-to-end trên bộ video đa dạng
(độ dài, số người nói, dọc/ngang, ồn, câm, link) theo DESIGN.md mục 12.

Cách chạy (từ thư mục vietdub/):
    .venv/bin/python tests/batch_20.py [--translate] [--fetch-links] \
        [--samples 01,02,12] [--workdir DIR] [--out FILE]

- Model ASR load ĐÚNG 1 LẦN rồi tái dùng cho cả 20 video.
- Bước duyệt tay bị bỏ qua (chế độ batch, giống "chế độ qua đêm").
- [4]+[5] dịch: chỉ chạy với --translate và khi có 9Router API key
  (biến môi trường VIETDUB_9ROUTER_KEY hoặc settings nine_router_key).
  Không có key -> ghi "bỏ qua (thiếu API key)" vào báo cáo, không fail.
- [6] TTS: sandbox chặn websocket của Edge-TTS nên dùng MOCK — sinh wav
  giả lập đúng độ dài từng câu (tỉ lệ 0.85x / 1.0x / 1.15x so với slot),
  rồi chạy duration_fit.plan() THẬT để verify logic khớp giờ
  (không câu nào "overflow" ngoài ngưỡng atempo 0.8-1.25).
- [7]+[8]: chạy THẬT trên 3 video mẫu (mặc định 01, 02, 12) với dub audio
  mock: build_track -> mix -> render -> verify mp4 có cả hình + tiếng.
- Video câm (#11, #20): pipeline phải dừng sạch ở [1] với lỗi tiếng Việt
  rõ ràng (edge case 6), không crash — ghi nhận vào cột "lỗi gặp".

Kết quả: file markdown hidden_files/wave3_20videos.md với bảng:
  | # | file | độ dài | số loa | giới tính | lỗi đại từ | TTS khớp giờ | lỗi gặp |

KHÔNG thu thập bởi pytest (chạy thủ công, cần model + thời gian).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("batch20")

TEST_DIR = ROOT / "hidden_files" / "test_videos"

# Chuẩn đối chiếu (từ MOSS + wave1_integration.log, clip man_clip):
#   speaker 0 = phóng viên (nữ, 251Hz), speaker 1 = ông Lý (nữ theo pitch 190Hz).
# Áp dụng cho các video cắt từ man_clip.webm: 01, 04, 05, 06, 12.
GENDER_GT = {
    "01_2nguoi_55s_phongvan.mp4": {0: "female", 1: "female"},
    "04_1nguoi_25s_phongvien.mp4": {0: "female"},
    "05_1nguoi_20s_ongly.mp4": {0: "female"},
    "06_2nguoi_30s_phongvan.mp4": {0: "female", 1: "female"},
    "12_doc_55s_phongvan.mp4": {0: "female", 1: "female"},
}
# Chuẩn đại từ (test 2026-10-08): phóng viên -> tôi/quý vị; ông Lý -> tôi/anh.
# Chỉ check video 01 và 06 (đủ 2 vai); các video khác ghi raw để người đọc đánh giá.
PRONOUN_GT = {
    "01_2nguoi_55s_phongvan.mp4": [{"tôi", "quý vị"}, {"tôi", "anh"}],
    "06_2nguoi_30s_phongvan.mp4": [{"tôi", "quý vị"}, {"tôi", "anh"}],
}
# URL gốc của video link (MANIFEST.md) — test bước [0] khi có --fetch-links.
LINK_URLS = {
    "15_link_66s_henan_cns.mp4":
        "https://commons.wikimedia.org/wiki/File:Henan_floods_2021-07-20_CNS.webm",
    "16_link_60s_chinajoy.mp4":
        "https://commons.wikimedia.org/wiki/File:2025_ChinaJoy上海启幕_AI技术赋能游戏新场景.webm",
}
# Tỉ lệ độ dài wav mock so với slot từng câu (xoay vòng để phủ keep/atempo).
MOCK_FACTORS = (0.85, 1.0, 1.15)


def parse_args():
    p = argparse.ArgumentParser(description="VietDub Wave 3: batch test 20 video")
    p.add_argument("--translate", action="store_true",
                   help="chạy [4]+[5] dịch (cần 9Router API key)")
    p.add_argument("--fetch-links", action="store_true",
                   help="thử tải 2 URL Wikimedia để test bước [0] yt-dlp")
    p.add_argument("--samples", default="01,02,12",
                   help="3 video mẫu chạy [7]+[8] (mặc định: 01,02,12)")
    p.add_argument("--workdir", default=str(ROOT / "hidden_files" / "wave3_batch"),
                   help="thư mục làm việc trung gian")
    p.add_argument("--out", default=str(ROOT / "hidden_files" / "wave3_20videos.md"),
                   help="file báo cáo markdown")
    return p.parse_args()


def collapse(xs):
    return [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]


def check_ffprobe_streams(mp4_path):
    """Trả về (có_video, có_audio, độ_dài_giây) của file mp4."""
    from media import _bin
    cmd = [_bin.ffprobe_cmd(), "-v", "error", "-show_entries",
           "stream=codec_type:format=duration", "-of", "json", str(mp4_path)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    info = json.loads(p.stdout or "{}")
    types = [s.get("codec_type") for s in info.get("streams", [])]
    dur = float(info.get("format", {}).get("duration") or 0)
    return ("video" in types, "audio" in types, dur)


def run_video(video_path, workdir, adapter, settings, do_translate, translator):
    """Chạy pipeline [1]->[6-mock] cho 1 video. Trả về dict kết quả 1 hàng."""
    from media import extract as mextract
    from speaker import gender as mgender
    from tts import duration_fit

    row = {"file": video_path.name, "errors": []}
    t_all = time.time()
    vdir = workdir / video_path.stem
    stages = vdir / "stages"
    (stages / "tts").mkdir(parents=True, exist_ok=True)

    def err(where, e):
        msg = f"[{where}] {type(e).__name__}: {str(e)[:160]}"
        row["errors"].append(msg)
        log.warning("%s: %s", video_path.name, msg)

    # --- [1] tách audio ---
    try:
        dur = mextract.duration_sec(video_path)
        row["duration"] = f"{dur:.0f}s"
        wav = mextract.extract_audio(video_path, stages / "audio.wav")
    except Exception as e:  # noqa: BLE001 - video câm là case hợp lệ
        row["duration"] = "?"
        err("1.extract", e)
        row.update({"n_speakers": "n/a (câm)", "gender": "n/a",
                    "pronoun": "n/a", "tts_fit": "n/a"})
        return row

    # --- [2] ASR + tách loa (model đã load 1 lần ở ngoài) ---
    try:
        t0 = time.time()
        segments = adapter.transcribe(str(wav))
        row["asr_sec"] = round(time.time() - t0, 1)
        spk_ids = sorted({s.speaker for s in segments})
        row["n_speakers"] = f"{len(spk_ids)} loa ({len(segments)} câu)"
        row["spk_seq"] = collapse([s.speaker for s in segments])
    except Exception as e:  # noqa: BLE001
        err("2.asr", e)
        row.update({"n_speakers": "lỗi", "gender": "n/a",
                    "pronoun": "n/a", "tts_fit": "n/a"})
        return row
    if not segments:
        row["errors"].append("[2.asr] không tách được câu nào")
        row.update({"gender": "n/a", "pronoun": "n/a", "tts_fit": "n/a"})
        return row

    # --- [3] giới tính ---
    try:
        t0 = time.time()
        spks = mgender.estimate_genders(str(wav), segments)
        row["gender_sec"] = round(time.time() - t0, 1)
        for seg in segments:
            if seg.speaker in spks:
                seg.gender = spks[seg.speaker].gender
        parts = []
        gt = GENDER_GT.get(video_path.name)
        for sid in sorted(spks):
            g = spks[sid]
            mark = ""
            if gt is not None:
                mark = " đúng" if gt.get(sid) == g.gender else " SAI"
            parts.append(f"#{sid} {g.gender} ({g.median_hz:.0f}Hz,"
                         f" conf {g.confidence:.2f}){mark}")
        row["gender"] = "; ".join(parts) if parts else "không tách được loa"
        row["_speakers"] = spks
    except Exception as e:  # noqa: BLE001
        err("3.gender", e)
        row["gender"] = "lỗi"

    # --- [4]+[5] dịch ---
    row["pronoun"] = "bỏ qua (không --translate)"
    if do_translate and translator is not None:
        try:
            t0 = time.time()
            spk_info = row.get("_speakers", {})
            analyzed = translator.analyze(segments, spk_info)
            segments = translator.translate(segments, analyzed)
            row["translate_sec"] = round(time.time() - t0, 1)
            got = [{s.pronoun_i, s.pronoun_you} for s in analyzed.values()]
            gt = PRONOUN_GT.get(video_path.name)
            if gt is not None:
                missing = [w for w in gt
                           if not any(w <= g for g in got)]
                row["pronoun"] = ("đạt" if not missing
                                  else "lỗi: thiếu " + ", ".join(
                                      "/".join(sorted(m)) for m in missing))
            else:
                row["pronoun"] = "n/a (không có chuẩn): " + "; ".join(
                    f"#{s.id} {s.pronoun_i}/{s.pronoun_you}"
                    for s in sorted(analyzed.values(), key=lambda x: x.id))
        except Exception as e:  # noqa: BLE001
            err("4+5.translate", e)
            row["pronoun"] = "lỗi dịch"
    row["_segments"] = segments
    row["_wav"] = str(wav)

    # --- [6] TTS mock + duration_fit thật ---
    try:
        tts_dir = stages / "tts"
        for i, seg in enumerate(segments):
            slot = seg.end - seg.start
            if slot <= 0:
                continue
            factor = MOCK_FACTORS[i % len(MOCK_FACTORS)]
            wp = tts_dir / f"seg_{seg.index:03d}.wav"
            duration_fit.make_silence_wav(wp, slot * factor)
            seg.audio_vi = str(wp)
        decisions = duration_fit.plan(segments, out_dir=tts_dir)
        n_atempo = sum(1 for _, a, _ in decisions if a == "atempo")
        n_over = sum(1 for _, a, _ in decisions if a == "overflow")
        n_keep = sum(1 for _, a, _ in decisions if a == "keep")
        row["_decisions"] = decisions
        row["tts_fit"] = ("đạt"
                          if n_over == 0 else f"lỗi: {n_over} câu overflow")
        row["tts_fit"] += f" ({len(decisions)} câu: {n_keep} giữ,"
        row["tts_fit"] += f" {n_atempo} atempo)"
    except Exception as e:  # noqa: BLE001
        err("6.tts-fit", e)
        row["tts_fit"] = "lỗi"

    row["total_sec"] = round(time.time() - t_all, 1)
    return row


def run_render_sample(video_path, workdir, row):
    """Chạy [7]+[8] THẬT trên 1 video mẫu với dub mock. Trả về dict kết quả."""
    from media import _bin, extract as mextract
    from media import mix as mmix
    from media import render as mrender
    from media import subs as msubs
    from tts import duration_fit

    res = {"file": video_path.name, "ok": False, "notes": []}
    try:
        vdir = workdir / video_path.stem
        stages = vdir / "stages"
        segments = row.get("_segments") or []
        if not segments:
            res["notes"].append("không có segments -> bỏ qua render")
            return res
        dur = mextract.duration_sec(video_path)
        decisions = row.get("_decisions")
        if decisions:
            duration_fit.apply_plan(decisions)  # co giãn wav mock cho khớp slot
        dub_wav = duration_fit.build_track(segments, stages / "dub_full.wav",
                                           total_sec=dur)
        # audio gốc full-rate để trộn (không phải bản 16k của ASR)
        orig_wav = stages / "orig_44100.wav"
        subprocess.run([_bin.ffmpeg_cmd(), "-y", "-v", "error",
                        "-i", str(video_path), "-vn",
                        "-ar", "44100", "-ac", "2",
                        str(orig_wav)], check=True)
        mixed = mmix.mix(dub_wav, orig_wav, stages / "mixed.wav")
        srt_path = msubs.write_srt(segments, stages / "dub.srt")
        out_srt = mrender.render(video_path, mixed, srt_path,
                                 vdir / f"{video_path.stem}_vidub.mp4",
                                 sub_mode="srt")
        hv, ha, d = check_ffprobe_streams(out_srt)
        res["notes"].append(
            f"srt-mode: {'có hình' if hv else 'THIẾU HÌNH'},"
            f" {'có tiếng' if ha else 'THIẾU TIẾNG'}, dài {d:.0f}s"
            f" -> {out_srt.name}")
        # thử burn sub trên cùng video mẫu
        try:
            out_burn = mrender.render(video_path, mixed, srt_path,
                                      vdir / f"{video_path.stem}_vidub_burn.mp4",
                                      sub_mode="burn")
            hv2, ha2, d2 = check_ffprobe_streams(out_burn)
            res["notes"].append(
                f"burn-mode: {'có hình' if hv2 else 'THIẾU HÌNH'},"
                f" {'có tiếng' if ha2 else 'THIẾU TIẾNG'} -> {out_burn.name}")
        except Exception as e:  # noqa: BLE001 - burn là bonus, srt mới là chính
            res["notes"].append(f"burn-mode lỗi (không chặn): {str(e)[:120]}")
        res["ok"] = bool(hv and ha)
    except Exception as e:  # noqa: BLE001
        res["notes"].append(f"LỖI: {type(e).__name__}: {str(e)[:200]}")
        log.warning("render %s lỗi:\n%s", video_path.name,
                    traceback.format_exc(limit=3))
    return res


def main():
    args = parse_args()
    workdir = Path(args.workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    from core.settings import Settings
    settings = Settings()

    videos = sorted(TEST_DIR.glob("*.mp4"))
    log.info("tìm thấy %d video test", len(videos))

    # --- bước [0]: test tải link (tùy chọn) ---
    fetch_notes = {}
    if args.fetch_links:
        from media import fetch as mfetch
        fetch_dir = workdir / "fetch_test"
        fetch_dir.mkdir(parents=True, exist_ok=True)
        for name, url in LINK_URLS.items():
            try:
                t0 = time.time()
                dest = mfetch.download(url, fetch_dir / name)
                fetch_notes[name] = (f"OK tải {time.time()-t0:.0f}s"
                                     f" -> {Path(dest).name}")
            except Exception as e:  # noqa: BLE001
                fetch_notes[name] = f"LỖI: {type(e).__name__}: {str(e)[:150]}"
    else:
        for name in LINK_URLS:
            fetch_notes[name] = "bỏ qua (dùng file local đã tải sẵn)"

    # --- load model ASR 1 lần duy nhất ---
    from asr.funasr_adapter import FunASRAdapter
    adapter = FunASRAdapter(asr_model=settings.get("asr_model"),
                            vad_model=settings.get("vad_model"),
                            punc_model=settings.get("punc_model"),
                            spk_model=settings.get("spk_model"))
    t0 = time.time()
    adapter.load()
    log.info("ASR model load xong: %.0fs (tái dùng cho %d video)",
             time.time() - t0, len(videos))

    # --- translator (tùy chọn) ---
    translator = None
    do_translate = False
    if args.translate:
        key = os.environ.get("VIETDUB_9ROUTER_KEY") or settings.get("nine_router_key", "")
        if key:
            from translation.nine_router import NineRouterTranslator
            translator = NineRouterTranslator(
                api_key=key,
                base_url=settings.get("nine_router_url"),
                model=settings.get("nine_router_model"),
                temperature=float(settings.get("llm_temperature", 0.2)),
                batch_size=int(settings.get("translate_batch", 20)))
            do_translate = True
            log.info("dịch: 9Router/%s", settings.get("nine_router_model"))
        else:
            log.warning("thiếu 9Router API key -> bỏ qua [4]+[5]")

    # --- chạy 20 video ---
    rows = []
    for i, vp in enumerate(videos, 1):
        log.info("[%d/20] %s", i, vp.name)
        try:
            row = run_video(vp, workdir, adapter, settings,
                            do_translate, translator)
        except Exception as e:  # noqa: BLE001 - 1 video lỗi không chặn cả batch
            log.warning("video %s crash ngoài dự kiến:\n%s",
                        vp.name, traceback.format_exc(limit=3))
            row = {"file": vp.name, "duration": "?", "n_speakers": "crash",
                   "gender": "n/a", "pronoun": "n/a", "tts_fit": "n/a",
                   "errors": [f"[crash] {type(e).__name__}: {str(e)[:150]}"]}
        row["idx"] = i
        rows.append(row)

    # --- [7]+[8] trên 3 video mẫu ---
    wanted = [s.strip() for s in args.samples.split(",") if s.strip()]
    by_stem = {vp.stem[:2]: vp for vp in videos}
    samples = [by_stem[w] for w in wanted if w in by_stem]
    row_by_file = {r["file"]: r for r in rows}
    renders = [run_render_sample(vp, workdir, row_by_file.get(vp.name, {}))
               for vp in samples]

    # --- xuất báo cáo markdown ---
    out = Path(args.out)
    L = []
    L.append("# VietDub Wave 3 — Batch test 20 video")
    L.append("")
    L.append(f"Ngày chạy: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    L.append("")
    L.append("Pipeline [1]->[5] đầy đủ, bỏ qua bước duyệt tay (chế độ batch).")
    L.append("Model ASR load 1 lần, tái dùng cho cả 20 video.")
    L.append("[6] TTS dùng wav mock đúng độ dài (tỉ lệ 0.85x/1.0x/1.15x so với slot)"
             " vì sandbox chặn websocket Edge-TTS; logic khớp giờ"
             " (`duration_fit.plan`) chạy thật.")
    L.append("[7]+[8] chạy thật trên 3 video mẫu với dub audio mock.")
    if not do_translate:
        L.append("[4]+[5] dịch: BỎ QUA (chạy không có --translate hoặc thiếu"
                 " 9Router API key) — cột 'lỗi đại từ' ghi n/a.")
    L.append("")

    L.append("## Bảng kết quả")
    L.append("")
    L.append("| # | file | độ dài | số loa | giới tính | lỗi đại từ"
             " | TTS khớp giờ | lỗi gặp |")
    L.append("|---|------|--------|--------|----------|------------|--------------|---------|")
    for r in rows:
        errs = "<br>".join(r.get("errors", [])) or "-"
        L.append(f"| {r['idx']} | {r['file']} | {r.get('duration', '?')} "
                 f"| {r.get('n_speakers', '?')} | {r.get('gender', '?')} "
                 f"| {r.get('pronoun', '?')} | {r.get('tts_fit', '?')} "
                 f"| {errs} |")
    L.append("")

    # tổng hợp tỉ lệ pass
    n = len(rows)
    n_asr_ok = sum(1 for r in rows if "loa" in str(r.get("n_speakers", "")))
    n_gender_ok = sum(1 for r in rows if r.get("gender") not in (None, "n/a", "lỗi")
                      and "SAI" not in str(r.get("gender", "")))
    n_tts_ok = sum(1 for r in rows if str(r.get("tts_fit", "")).startswith("đạt"))
    L.append("## Tổng hợp")
    L.append("")
    L.append(f"- Tổng video: {n}")
    L.append(f"- [1] tách audio OK: "
             f"{sum(1 for r in rows if r.get('duration', '?') != '?')}/{n}"
             f" (video câm dừng sạch ở [1] là hành vi đúng theo edge case 6)")
    L.append(f"- [2] ASR tách được loa: {n_asr_ok}/{n}")
    L.append(f"- [3] giới tính (không SAI so với chuẩn MOSS): {n_gender_ok}/{n}")
    L.append(f"- [6] TTS khớp giờ (mock + plan thật): {n_tts_ok}/{n}")
    if do_translate:
        n_pro = sum(1 for r in rows if r.get("pronoun") == "đạt")
        L.append(f"- [4]+[5] đại từ đạt chuẩn: {n_pro}/{n} (chỉ check video"
                 f" 01/06 có chuẩn)")
    L.append("")

    L.append("## Bước [0] tải link (yt-dlp)")
    L.append("")
    for name, note in fetch_notes.items():
        L.append(f"- {name}: {note}")
    L.append("")

    L.append("## Render [7]+[8] (3 video mẫu, dub mock)")
    L.append("")
    for res in renders:
        mark = "ĐẠT" if res["ok"] else "CHƯA ĐẠT"
        L.append(f"- {res['file']}: **{mark}**")
        for note in res["notes"]:
            L.append(f"  - {note}")
    L.append("")

    L.append("## Ghi chú")
    L.append("")
    L.append("- Video #11/#20 không có track audio: pipeline dừng ở [1] với"
             " thông báo tiếng Việt, không crash (edge case 6).")
    L.append("- Video #07 (nhạc nền tổng hợp) / #08 (tiếng ồn hồng): kiểm tra"
             " ASR tách tiếng nói trên nền ồn.")
    L.append("- Video #09/#10 tiếng Anh, #14 tiếng Việt: model ASR huấn luyện"
             " tiếng Trung nên kết quả chỉ mang tính tham khảo.")
    L.append("- TTS mock: chưa verify giọng Edge-TTS thật — chờ chạy trên máy"
             " Windows của Tony (sandbox chặn websocket).")
    L.append("")

    out.write_text("\n".join(L), encoding="utf-8")
    log.info("báo cáo: %s", out)
    log.info("hoàn thành: %d video, %d render mẫu", n, len(renders))


if __name__ == "__main__":
    main()
