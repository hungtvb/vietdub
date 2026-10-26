"""Decoded real video acceptance gate: coverage, frame loss, unrelated edits."""
import pytest

cv2=pytest.importorskip("cv2")
np=pytest.importorskip("numpy")
from media.visual_acceptance import audit_video


def _make(path, *, frames=20, overlay_at=None):
    wr=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*"mp4v"),10,(160,96))
    assert wr.isOpened()
    for i in range(frames):
        f=np.full((96,160,3),80,np.uint8)
        if overlay_at is not None and i>=overlay_at:
            f[60:84,20:145]=(200,240,30)
        wr.write(f)
    wr.release()


def test_acceptance_detects_shorter_video_even_when_valid_mp4(tmp_path):
    a,b=tmp_path/"original.mp4",tmp_path/"short.mp4"
    _make(a,frames=20);_make(b,frames=18)
    plan={"regions":[]}
    r=audit_video(a,b,plan)
    assert not r["pass_structural_checks"]
    assert r["source_frames"]==20 and r["output_frames"]==18
    assert any("frame loss" in x for x in r["issues"])


def test_acceptance_detects_missing_real_subtitle_coverage(tmp_path):
    video=tmp_path/"v.mp4"
    _make(video)
    p={"regions":[{"kind":"subtitle","start":1.0,"end":2.0,
                   "box":[15,60,150,84]}]}
    r=audit_video(video,video,p,required_subtitle_times=[.5,1.5])
    assert not r["pass_structural_checks"]
    assert any("0.50s" in x for x in r["issues"])
    assert r["boundary_jumps"]==[]


def test_acceptance_catches_unexpected_mask_onset_pop(tmp_path):
    source,out=tmp_path/"src.mp4",tmp_path/"pop.mp4"
    _make(source)
    _make(out,overlay_at=5)
    plan={"regions":[{"kind":"subtitle","start":.5,"end":1.9,
                      "box":[20,60,145,84]}]}
    r=audit_video(source,out,plan)
    assert not r["pass_structural_checks"]
    assert r["boundary_jumps"]
    assert r["boundary_jumps"][0]["at_seconds"] == .5


def test_acceptance_same_video_passes_structure_without_claiming_visual_quality(tmp_path):
    v=tmp_path/"same.mp4"
    _make(v)
    report=audit_video(v,v,{"regions":[]})
    assert report["pass_structural_checks"]
    assert report["source_frames"]==report["output_frames"]==20
    assert "do not prove" in report["quality_warning"].lower()
