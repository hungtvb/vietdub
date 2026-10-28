"""Actual decoded-video regressions for operator-selected visual blur regions."""
import json
import shutil

import cv2
import numpy as np
import pytest

from media.visual_user_regions import (
    UserRegionError, apply_user_regions, validate_plan,
    validate_region, video_metadata
)
from media.visual_cleanup import VisualCleanup, Config


def _frame():
    y,x=np.mgrid[:96,:160]
    image=np.zeros((96,160,3),np.uint8)
    image[:,:,0]=((x*3+y*4)%190+30).astype(np.uint8)
    image[:,:,1]=((x*5+y*2)%190+25).astype(np.uint8)
    image[:,:,2]=((x*2+y*5)%190+35).astype(np.uint8)
    return image


def _region(start=.3,end=.8,mode="blur"):
    return {"source":"user","start":start,"end":end,
            "box":[30,51,135,85],"kind":"subtitle",
            "mode":mode,"strength":18,"feather":2}


@pytest.mark.parametrize("mode",["blur","pixelate","inpaint"])
def test_preview_only_edits_exact_user_rectangle(mode):
    before=_frame()
    after=apply_user_regions(before,[_region(mode=mode)],5,10)
    assert not np.array_equal(after[59:80,45:125],
                              before[59:80,45:125])
    assert np.array_equal(after[:45],before[:45])
    assert np.array_equal(after[:, :25],before[:, :25])
    assert np.array_equal(after[:, 140:],before[:, 140:])


def test_manual_timing_uses_exact_frame_interval_not_ocr_samples():
    raw=_frame()
    r=_region(start=.3,end=.8)
    for n in range(12):
        result=apply_user_regions(raw,[r],n,10)
        changed=not np.array_equal(result,raw)
        assert changed == (3<=n<8),n


@pytest.mark.parametrize("box",[
    [-1,0,20,30],[0,5,161,40],[50,10,49,20],[5,5,5,8],
    [0,100,50,110],[10,10,30]
])
def test_invalid_geometry_fails_closed(box):
    with pytest.raises(UserRegionError):
        validate_region({**_region(),"box":box},160,96,1.2)


@pytest.mark.parametrize("wrong",[
    {"start":.8,"end":.7},{"start":-1,"end":.8},
    {"mode":"magic"},{"strength":100},{"feather":float("nan")},
    {"end":2.0}
])
def test_invalid_interval_or_mode_fails_closed(wrong):
    with pytest.raises(UserRegionError):
        validate_region({**_region(),**wrong},160,96,1.2)


def _video(path):
    wr=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*"mp4v"),10,(160,96))
    assert wr.isOpened()
    sample=_frame()
    for i in range(12):
        fr=sample.copy()
        cv2.putText(fr,"SAMPLE",(38,76),cv2.FONT_HERSHEY_SIMPLEX,
                    .6,(255,255,255),2,cv2.LINE_AA)
        wr.write(fr)
    wr.release()


def test_source_bound_manual_plan_rejects_other_video_and_stale_frames(tmp_path):
    src=tmp_path/"a.mp4"; other=tmp_path/"b.mp4"
    _video(src);_video(other)
    meta=video_metadata(src)
    plan={**meta,"regions":[_region()]}
    _,rows=validate_plan(plan,src)
    assert len(rows)==1
    with pytest.raises(UserRegionError):
        validate_plan(plan,other)
    with pytest.raises(UserRegionError):
        validate_plan({**plan,"frames":100},src)


@pytest.mark.skipif(not shutil.which("ffmpeg"),reason="FFmpeg required")
def test_real_mp4_manual_blur_without_ocr_weights(tmp_path):
    source=tmp_path/"original.mp4"; output=tmp_path/"clean.mp4"
    _video(source)
    meta=video_metadata(source)
    plan={**meta,"regions":[_region(start=.3,end=.8,mode="pixelate")],
          "reviewed":True}
    # No OCR model is installed, and render must not invoke one here.
    output_file=VisualCleanup(Config(mode="blur",auto_logo=False)).render(
        source,output,plan)
    assert output_file.is_file()
    origin=cv2.VideoCapture(str(source))
    clean=cv2.VideoCapture(str(output))
    for n in range(12):
        ok0,a=origin.read();ok1,b=clean.read()
        assert ok0 and ok1
        # Outside the approved rectangle, only H264 encoding error allowed.
        outside=np.mean(np.abs(a[10:40].astype(float)-b[10:40].astype(float)))
        assert outside<11,(n,outside)
        inside=np.mean(np.abs(a[59:82,40:128].astype(float)-
                              b[59:82,40:128].astype(float)))
        if 3<=n<8:
            assert inside>8,(n,inside)
        else:
            assert inside<11,(n,inside)
    assert not clean.read()[0]
    origin.release();clean.release()



@pytest.mark.skipif(not shutil.which("ffmpeg"),reason="FFmpeg required")
def test_render_fractional_manual_times_activate_on_rounded_frame(tmp_path):
    video=tmp_path/"src.mp4"; output=tmp_path/"out.mp4"
    _video(video)
    # .31*10 rounds to frame 3, .79*10 rounds to 8 (end exclusive).
    plan={**video_metadata(video),"regions":[
        _region(start=.31,end=.79,mode="pixelate")]}
    VisualCleanup(Config(mode="blur",auto_logo=False)).render(
        video,output,plan)
    a=cv2.VideoCapture(str(video)); b=cv2.VideoCapture(str(output))
    for frame_no in range(12):
        oka,raw=a.read();okb,clean=b.read()
        assert oka and okb
        roi=np.s_[58:80,42:126]
        change=float(np.mean(np.abs(raw[roi].astype(float)-
                                   clean[roi].astype(float))))
        if 3<=frame_no<8:
            assert change>8,(frame_no,change)
        else:
            assert change<11,(frame_no,change)
    a.release();b.release()


def test_json_plan_roundtrip_and_no_autodetection(tmp_path):
    source=tmp_path/"video.mp4";_video(source)
    plan={**video_metadata(source),"regions":[_region()]}
    target=tmp_path/"reviewed.json"
    target.write_text(json.dumps(plan),encoding="utf-8")
    loaded=json.loads(target.read_text(encoding="utf-8"))
    _,manual=validate_plan(loaded,source)
    assert manual[0]["source"]=="user"
    assert manual[0]["box"]==[30,51,135,85]
