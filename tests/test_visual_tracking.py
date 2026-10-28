"""End-to-end encoded/decoded tests for explicit moving-logo region tracking.

The overlay is synthetic on textured scene frames so ground-truth position is
known exactly. This is a motion-tracking regression, not a claim of full
arbitrary movie accuracy.
"""
import shutil

import cv2
import numpy as np
import pytest

from media.visual_tracking import TrackingError, track_region
from media.visual_cleanup import VisualCleanup, Config
from media.visual_user_regions import validate_region, video_metadata


def _movie(path, *, count=30, cut_at=None, flat_logo=False):
    fps,w,h=10,320,180
    writer=cv2.VideoWriter(
        str(path),cv2.VideoWriter_fourcc(*"mp4v"),fps,(w,h))
    assert writer.isOpened()
    rng=np.random.default_rng(7)
    first=rng.integers(40,110,(h,w,3),dtype=np.uint8)
    second=rng.integers(140,220,(h,w,3),dtype=np.uint8)
    for i in range(count):
        frame=(second if cut_at is not None and i>=cut_at else first).copy()
        x,y=45+i//2,54+i//5
        cv2.rectangle(frame,(x,y),(x+65,y+30),(22,26,203),-1)
        if not flat_logo:
            cv2.putText(frame,"MARK",(x+5,y+22),
                        cv2.FONT_HERSHEY_SIMPLEX,.53,(255,255,255),2)
        writer.write(frame)
    writer.release()


def _region():
    return {
        "source":"user","start":0.0,"end":3.0,
        "box":[45,54,111,85],"kind":"logo",
        "mode":"pixelate","strength":14,"feather":0,
        "tracking":"template",
        "keyframes":[{"frame":0,"box":[45,54,111,85]}]
    }


def test_moving_logo_follows_ground_truth_in_encoded_video(tmp_path):
    video=tmp_path/"motion.mp4";_movie(video)
    tracks=track_region(video,_region())
    assert set(tracks)==set(range(30))
    errors=[]
    for frame,point in tracks.items():
        x,y=45+frame//2,54+frame//5
        errors.append(max(abs(point.box[0]-x),
                          abs(point.box[1]-y)))
    assert max(errors)<=2
    assert min(point.confidence for point in tracks.values())>.68


def test_tracking_rejects_cross_shot_without_user_keyframe(tmp_path):
    video=tmp_path/"cut.mp4";_movie(video,cut_at=16)
    with pytest.raises(TrackingError,match="scene cut"):
        track_region(video,_region())


def test_manual_keyframe_on_shot_cut_can_reanchor(tmp_path):
    video=tmp_path/"cut.mp4";_movie(video,cut_at=16)
    plan=_region()
    plan["keyframes"].append({
        "frame":16,"box":[45+16//2,54+16//5,
                          111+16//2,85+16//5]})
    points=track_region(video,plan)
    assert points[16].source=="keyframe"
    assert len(points)==30
    assert points[17].source=="template"


def test_static_uniform_logo_rejected_no_false_confidence(tmp_path):
    video=tmp_path/"uniform.mp4";_movie(video,flat_logo=True)
    with pytest.raises(TrackingError,match="little detail"):
        track_region(video,_region())


def test_invalid_keyframe_dimensions_fail_closed(tmp_path):
    video=tmp_path/"motion.mp4";_movie(video)
    region=_region()
    region["keyframes"].append({"frame":8,"box":[50,56,90,75]})
    with pytest.raises(TrackingError,match="constant rectangle size"):
        track_region(video,region)


def test_keyframes_preserved_by_operator_review_plan():
    plan=validate_region(_region(),320,180,3.0)
    assert plan["tracking"]=="template"
    assert plan["keyframes"]==[{"frame":0,"box":[45,54,111,85]}]


@pytest.mark.skipif(not shutil.which("ffmpeg"),reason="FFmpeg required")
def test_actual_render_follows_moving_logo_and_preserves_outside(tmp_path):
    video=tmp_path/"motion.mp4";result=tmp_path/"clean.mp4"
    _movie(video)
    plan={**video_metadata(video),"regions":[_region()]}
    out=VisualCleanup(Config(auto_logo=False)).render(video,result,plan)
    assert out.exists()
    original=cv2.VideoCapture(str(video))
    cleaned=cv2.VideoCapture(str(out))
    for i in range(30):
        ok0,a=original.read();ok1,b=cleaned.read()
        assert ok0 and ok1
        x,y=45+i//2,54+i//5
        inside=np.mean(np.abs(a[y+5:y+25,x+10:x+57].astype(float)-
                              b[y+5:y+25,x+10:x+57].astype(float)))
        outside=np.mean(np.abs(a[5:40,200:300].astype(float)-
                               b[5:40,200:300].astype(float)))
        assert inside>7,(i,inside)
        assert outside<12,(i,outside)
    assert not cleaned.read()[0]
    original.release();cleaned.release()


@pytest.mark.skipif(not shutil.which("ffmpeg"),reason="FFmpeg required")
def test_render_rejects_cut_without_writing_output(tmp_path):
    video=tmp_path/"cut.mp4";dest=tmp_path/"should-not-exist.mp4"
    _movie(video,cut_at=16)
    plan={**video_metadata(video),"regions":[_region()]}
    with pytest.raises(TrackingError,match="scene cut"):
        VisualCleanup(Config(auto_logo=False)).render(video,dest,plan)
    assert not dest.exists()
