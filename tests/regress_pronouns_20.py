#!/usr/bin/env python3
# VietDub — regression [4]+[5] (phân tích + dịch) trên bộ 20 video độc lập.
# Sau fix đại từ 2026-10-09 (prompt phân tầng + post-rule interviewee).
# Kiểm tra mỗi video: số câu vào == số câu ra, JSON hợp lệ (analyze/translate
# raise nếu fail sau retry), cặp đại từ từng loa, flag fallback vô lý.
# Video 01 có chuẩn GT: assert đạt.
import json
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.WARNING,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("regress")

TEST_DIR = ROOT / "hidden_files" / "test_videos"
WORKDIR = ROOT / "hidden_files" / "wave3b_regress"
OUT_MD = ROOT / "hidden_files" / "wave3b_pronoun_fix.md"

# 20 video độc lập (10 giữ + 10 mới từ Wikimedia Commons)
VIDEOS = [
    "01_2nguoi_55s_phongvan.mp4",
    "02_nhieunguoi_197s_tintuc.mp4",
    "03_nhieunguoi_240s_hoathinh.mp4",
    "09_en_45s_tos.mp4",
    "10_en_16s_input.mp4",
    "11_doc_10s_khongtieng.mp4",
    "14_vi_8s_ghep.mp4",
    "15_link_66s_henan_cns.mp4",
    "16_link_60s_chinajoy.mp4",
    "20_ngan_10s_khongtieng.mp4",
    "21_2nguoi_xizang_baodao.mp4",
    "22_nhieunguoi_xinjiang_jiangshu.mp4",
    "23_2nguoi_kelaideman_phongvan.mp4",
    "24_2nguoi_mianbaoshi_gushi.mp4",
    "25_2nguoi_majian_voa.mp4",
    "26_2nguoi_caodewang_voa.mp4",
    "27_2nguoi_adidas_ceo.mp4",
    "28_2nguoi_gracejin_voa.mp4",
    "29_2nguoi_tongrentang_ON.mp4",
    "30_doc_fumaohui_baodao.mp4",
]

PRONOUN_GT_01 = [{"tôi", "quý vị"}, {"tôi", "anh"}]


def run_one(video, adapter, translator):
    from media import extract as mextract
    from speaker import gender as mgender
    from project.schema import Speaker

    row = {"file": video, "errors": []}
    vp = TEST_DIR / video
    if not vp.exists():
        row["errors"].append("thiếu file")
        return row
    vdir = WORKDIR / Path(video).stem
    vdir.mkdir(parents=True, exist_ok=True)

    # [1] extract
    try:
        wav = mextract.extract_audio(vp, vdir / "audio.wav")
        row["duration"] = f"{mextract.duration_sec(vp):.0f}s"
    except Exception as e:
        row["note"] = f"câm/không audio -> dừng sạch [1] ({type(e).__name__})"
        return row

    # [2] ASR
    try:
        segments = adapter.transcribe(str(wav))
    except Exception as e:
        row["errors"].append(f"[2.asr] {type(e).__name__}: {str(e)[:120]}")
        return row
    n_in = len(segments)
    row["n_in"] = n_in
    if not n_in:
        row["note"] = "ASR ra 0 câu"
        return row

    # [3] gender
    try:
        spks = mgender.estimate_genders(str(wav), segments)
        speakers = {i: Speaker(id=i, gender=s.gender) for i, s in spks.items()}
        row["genders"] = {i: s.gender for i, s in spks.items()}
    except Exception as e:
        row["errors"].append(f"[3.gender] {type(e).__name__}")
        return row

    # [4] analyze + [5] translate
    try:
        analyzed = translator.analyze(segments, speakers)
        segments = translator.translate(segments, analyzed)
    except Exception as e:
        row["errors"].append(f"[4+5] {type(e).__name__}: {str(e)[:120]}")
        return row

    n_out = sum(1 for s in segments if s.text_vi)
    row["n_out"] = n_out
    row["line_match"] = "OK" if n_out == n_in else f"SAI ({n_in}->{n_out})"
    pairs = {i: f"{s.pronoun_i}/{s.pronoun_you}" for i, s in analyzed.items()}
    row["pronouns"] = pairs
    fb = [i for i, s in analyzed.items()
          if (s.pronoun_i, s.pronoun_you) == ("tôi", "bạn")]
    row["fallback_ban"] = fb  # speaker nào còn rớt về toi/ban

    if video.startswith("01_"):
        got = [{s.pronoun_i, s.pronoun_you} for s in analyzed.values()]
        missing = [w for w in PRONOUN_GT_01 if not any(w <= g for g in got)]
        row["GT_01"] = "PASS" if not missing else f"FAIL thiếu {missing}"
    return row


def main():
    from core.settings import Settings
    settings = Settings()
    from asr.funasr_adapter import FunASRAdapter
    adapter = FunASRAdapter(asr_model=settings.get("asr_model"),
                            vad_model=settings.get("vad_model"),
                            punc_model=settings.get("punc_model"),
                            spk_model=settings.get("spk_model"))
    log.warning("loading FunASR...")
    adapter.load()
    from translation.nine_router import NineRouterTranslator
    key = os.environ.get("VIETDUB_9ROUTER_KEY") or settings.get("nine_router_key", "")
    translator = NineRouterTranslator(
        api_key=key, base_url=settings.get("nine_router_url"),
        model=settings.get("nine_router_model"),
        temperature=float(settings.get("llm_temperature", 0.2)),
        batch_size=int(settings.get("translate_batch", 20)))
    log.warning("translator: 9Router/%s", settings.get("nine_router_model"))

    rows = []
    t0 = time.time()
    for i, v in enumerate(VIDEOS, 1):
        log.warning("[%d/20] %s", i, v)
        rows.append(run_one(v, adapter, translator))

    # --- báo cáo ---
    L = ["# VietDub — Regression [4]+[5] sau fix đại từ (2026-10-09)",
         "",
         f"Chạy: {time.strftime('%Y-%m-%d %H:%M')}, tổng {time.time()-t0:.0f}s.",
         "Fix: prompt phân tầng (phỏng vấn→tôi/anh, cấm fallback 'bạn' lười) +",
         "post-rule deterministic trong `translation/base.py::_post_rule_interviewee`.",
         "",
         "## Bảng kết quả",
         "",
         "| # | file | dài | câu vào/ra | cặp đại từ từng loa | fallback tôi/bạn | chuẩn GT |",
         "|---|------|-----|----------|---------------------|------------------|----------|"]
    npass = nfail = 0
    for i, r in enumerate(rows, 1):
        if "note" in r and "n_in" not in r:
            L.append(f"| {i} | {r['file']} | {r.get('duration','?')} | n/a | n/a | n/a | {r['note']} |")
            continue
        errs = "; ".join(r["errors"])
        pr = "; ".join(f"#{k} {v}" for k, v in r.get("pronouns", {}).items())
        fb = str(r.get("fallback_ban", []))
        gt = r.get("GT_01", "-")
        if gt == "PASS":
            npass += 1
        elif gt.startswith("FAIL"):
            nfail += 1
        flag = f" LỖI: {errs}" if errs else ""
        L.append(f"| {i} | {r['file']} | {r.get('duration','?')} | "
                 f"{r.get('n_in','?')}/{r.get('n_out','?')} {r.get('line_match','')} | "
                 f"{pr} | {fb} | {gt}{flag} |")
    L += ["",
          f"**Chuẩn GT video 01: {npass} PASS, {nfail} FAIL** (06 đã PASS ở bước verify riêng, "
          "không còn trong bộ 20 độc lập).",
          "",
          "## Ghi chú",
          "- fallback `tôi/bạn` còn lại ở các video không có chuẩn: người đọc đánh giá "
          "tính hợp lý theo ngữ cảnh (ví dụ talkshow bạn bè → hợp lý; tin tức → nên là anh/chị).",
          "- Video câm (11, 20) dừng sạch ở [1] là hành vi đúng (edge case 6).",
          "- 09/10 tiếng Anh, 14 tiếng Việt: ASR huấn luyện tiếng Trung, kết quả tham khảo."]
    OUT_MD.write_text("\n".join(L), encoding="utf-8")
    print(f"\n== GT_01: {npass} PASS / {nfail} FAIL ==")
    print("report:", OUT_MD)


if __name__ == "__main__":
    main()
