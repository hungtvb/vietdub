"""Opt-in LIVE smoke: downloads and executes PaddleOCR 3.x model on generated video.

Run only with VIETDUB_LIVE_OCR=1. No fake OCR detector is injected.
"""
import json
import os
import shutil
from pathlib import Path

import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")
from media.visual_cleanup import Config, VisualCleanup, PaddleDetector


@pytest.mark.skipif(os.getenv("VIETDUB_LIVE_OCR") != "1",
                    reason="Requires PaddleOCR/PaddlePaddle and model download")
@pytest.mark.skipif(not shutil.which("ffmpeg"),reason="ffmpeg unavailable")
def test_real_paddle_detects_and_blurs_burned_subtitles(tmp_path):
    video=tmp_path/"burned_subtitles.mp4"
    w,h,fps = 960,540,10
    writer=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*"mp4v"),fps,(w,h))
    assert writer.isOpened()
    for i in range(35):
        f=np.full((h,w,3), 70,np.uint8)
        # Moving geometry keeps the image video-like (not a still photograph).
        cv2.rectangle(f,(i*9%600+70,120),(i*9%600+150,290),(95,144,195),-1)
        cv2.rectangle(f,(100,400),(870,525),(0,0,0),-1)
        cv2.putText(f,"HELLO WORLD",(245,485),cv2.FONT_HERSHEY_SIMPLEX,1.8,(255,255,255),4,cv2.LINE_AA)
        writer.write(f)
    writer.release()
    assert video.is_file()
    detector=PaddleDetector()  # Real pretrained PaddleOCR 3.x; no fake/mock detector.
    engine=VisualCleanup(Config(sample_sec=.6,min_hits=2,
                                categories=("subtitle",),auto_logo=False),detector=detector)
    plan=engine.analyze(video, tmp_path/"plan.json")
    subtitles=[r for r in plan["regions"] if r["kind"] == "subtitle"]
    assert subtitles, "PaddleOCR found no subtitle regions: "+str(plan["regions"])
    assert any(r["box"][1] >= h*.68 for r in subtitles)
    rendered=engine.render(video,tmp_path/"blur.mp4",plan)
    assert rendered.is_file() and rendered.stat().st_size>5000
    cap=cv2.VideoCapture(str(rendered))
    ok, frame=cap.read()
    cap.release()
    assert ok and frame.shape[:2] == (h,w)

    # Persist actual pixel-level evidence from this very CI run, not a mock.
    evidence=Path("evidence/visual-cleanup-live")
    evidence.mkdir(parents=True,exist_ok=True)
    selected_frame=10   # t = 1.0s, safely inside the tracked text interval.
    def frame_at(path,index):
        cap=cv2.VideoCapture(str(path))
        cap.set(cv2.CAP_PROP_POS_FRAMES,index)
        ok,result=cap.read()
        cap.release()
        assert ok
        return result
    before=frame_at(video,selected_frame)
    after=frame_at(rendered,selected_frame)
    raw=list(detector.detect(before))
    assert raw, "Real PaddleOCR did not find the text at evidence timestamp"
    from media.visual_detection import detect_frame_candidates
    suggested = detect_frame_candidates(before, detector)
    assert suggested, "Multi-pass OCR suggestions missing real detected text"
    review_overlay = before.copy()
    for box, score in suggested:
        x1,y1,x2,y2 = box
        cv2.rectangle(review_overlay,(x1,y1),(x2,y2),(0,180,255),3)
        cv2.putText(review_overlay,f"REVIEW {score:.2f}",
                    (x1,max(18,y1-5)),cv2.FONT_HERSHEY_SIMPLEX,
                    .55,(0,180,255),2)
    assert cv2.imwrite(str(Path("evidence/visual-cleanup-live") /
                            "06_reviewable_multi_pass_OCR.png"), review_overlay) if Path(
                            "evidence/visual-cleanup-live").is_dir() else True
    active=[r for r in plan["regions"]
            if r["kind"]=="subtitle" and r["start"] <= selected_frame/fps < r["end"]]
    assert active, "No temporal OCR track active at evidence timestamp"
    overlay_ocr=before.copy()
    for box,score in raw:
        x1,y1,x2,y2=map(int,box)
        cv2.rectangle(overlay_ocr,(x1,y1),(x2,y2),(0,255,0),3)
        cv2.putText(overlay_ocr,f"OCR {score:.2f}",(max(0,x1),max(20,y1-6)),
                    cv2.FONT_HERSHEY_SIMPLEX,.65,(0,255,0),2)
    overlay_track=before.copy()
    for r in active:
        x1,y1,x2,y2=r["box"]
        cv2.rectangle(overlay_track,(x1,y1),(x2,y2),(0,170,255),3)
        label=f"TRACK {r['start']:.2f}s - {r['end']:.2f}s"
        cv2.putText(overlay_track,label,(max(0,x1),max(20,y1-10)),
                    cv2.FONT_HERSHEY_SIMPLEX,.6,(0,170,255),2)
    assert cv2.imwrite(str(evidence/"01_original.png"),before)
    assert cv2.imwrite(str(evidence/"02_live_paddleocr_boxes.png"),overlay_ocr)
    assert cv2.imwrite(str(evidence/"03_temporal_tracking.png"),overlay_track)
    assert cv2.imwrite(str(evidence/"04_blurred_result.png"),after)
    # At the detected text region, the pixels actually changed after blur.
    x1,y1,x2,y2=active[0]["box"]
    changed=float(np.mean(np.abs(before[y1:y2,x1:x2].astype(np.float32)-
                                 after[y1:y2,x1:x2].astype(np.float32))))
    assert changed > 2, f"Blur did not visibly alter detected text: {changed:.3f}"
    # Compare the same source/render frame in a contact sheet.
    panels=[]
    for title,shot in [
        ("1  Original",before),("2  PaddleOCR",overlay_ocr),
        ("3  Tracking",overlay_track),("4  Blur",after)
    ]:
        top=np.zeros((48,w,3),np.uint8)
        cv2.putText(top,title,(20,34),cv2.FONT_HERSHEY_SIMPLEX,1,(255,255,255),2)
        panels.append(np.vstack((top,shot)))
    comparison=np.hstack(panels)
    assert cv2.imwrite(str(evidence/"05_comparison.png"),comparison)
    report={
        "real_ocr":True,
        "detector":"PaddleOCR 3.x via PaddleDetector",
        "sample_video":"generated moving-scene video with burned-in English text",
        "frame_number":selected_frame,
        "timestamp_seconds":selected_frame/fps,
        "raw_ocr_boxes":[{"box":list(map(int,box)),"confidence":float(score)}
                         for box,score in raw],
        "reviewable_multi_pass_candidates": [
            {"box":list(box),"confidence":float(score)}
            for box,score in suggested],
        "temporal_regions":active,
        "mean_absolute_pixel_change_in_track":changed,
        "paths":sorted(p.name for p in evidence.glob("*.png")),
        "scope_note":"Generated English hard subtitles only; not a real-film/Chinese/logo quality benchmark."
    }
    (evidence/"evidence.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    (evidence/"full_ocr_plan.json").write_text(json.dumps(plan,indent=2),encoding="utf-8")
    print("VISUAL_EVIDENCE "+json.dumps({
        "ocr_boxes":len(raw),"tracks":len(active),
        "pixel_change":round(changed,2),
        "files":report["paths"]},sort_keys=True))
