"""Opt-in LIVE smoke: downloads and executes PaddleOCR 3.x model on generated video.

Run only with VIETDUB_LIVE_OCR=1. No fake OCR detector is injected.
"""
import os
import shutil

import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")
from media.visual_cleanup import Config, VisualCleanup


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
    engine=VisualCleanup(Config(sample_sec=.6,min_hits=2,
                                categories=("subtitle",),auto_logo=False))
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
