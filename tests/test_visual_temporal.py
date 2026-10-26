"""Actual encode/decode tests for reviewed clean-plate overlays (not OCR mocks)."""
import shutil

import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

from media.visual_cleanup import Config, VisualCleanup
from media.visual_temporal import TemporalCleanPlate, TemporalPlanError


def _fixture(path):
    w,h,fps=320,180,10
    writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*"mp4v"),fps,(w,h))
    assert writer.isOpened()
    truth=[]
    for i in range(24):
        y,x=np.mgrid[:h,:w]
        fr=np.zeros((h,w,3),np.uint8)
        fr[:,:,0]=np.uint8(75+25*np.sin((x+i)/18))
        fr[:,:,1]=np.uint8(85+25*np.sin(y/15))
        fr[:,:,2]=np.uint8(110+25*np.cos(x/22))
        cv2.circle(fr,(160+i//3,145),13,(120,150,190),-1)
        truth.append(fr.copy())
        if 5<=i<18:
            overlay=fr.copy()
            cv2.rectangle(overlay,(0,116),(270,165),(0,0,0),-1)
            fr=cv2.addWeighted(fr,.45,overlay,.55,0)
            cv2.putText(fr,"TITLE",(35,146),cv2.FONT_HERSHEY_SIMPLEX,
                        1,(255,255,255),3,cv2.LINE_AA)
        # A distinct always-on colored logo patch can be replaced by a
        # manually approved same-size clean texture donor.
        writer.write(fr)
    writer.release()
    return truth


def _plan(path):
    return {
        "version":1, "source":str(path.resolve()),"width":320,"height":180,
        "fps":10.0,"frames":24,
        "regions":[{
            "start":0.3,"end":1.8,
            "box":[0,114,273,168],
            "kind":"subtitle", "source":"temporal-clean-plate",
            "confidence":1.0,
            "reference_frames":[2,21],
            "flow_height":110,
            "blend_frames":[11,15],
            "feather":2.5
        }]
    }


@pytest.mark.skipif(not shutil.which("ffmpeg"),reason="ffmpeg unavailable")
def test_temporal_removes_full_caption_band_and_preserves_other_pixels(tmp_path):
    video=tmp_path/"source.mp4"
    truth=_fixture(video)
    plan=_plan(video)
    output=tmp_path/"clean.mp4"
    engine=VisualCleanup(Config(auto_logo=False))
    engine.render(video,output,plan)
    reader=cv2.VideoCapture(str(output))
    assert reader.isOpened()
    frames=[]
    while True:
        ok,fr=reader.read()
        if not ok:break
        frames.append(fr)
    reader.release()
    assert len(frames)==24
    original=cv2.VideoCapture(str(video))
    for i in (5,8,12,17):
        original.set(cv2.CAP_PROP_POS_FRAMES,i)
        ok,before=original.read()
        assert ok
        a=frames[i]
        roi=np.s_[121:157,23:254]
        before_error=np.mean(np.abs(before[roi].astype(float)-truth[i][roi].astype(float)))
        after_error=np.mean(np.abs(a[roi].astype(float)-truth[i][roi].astype(float)))
        assert after_error < before_error*.70, (i,before_error,after_error)
        # H264 re-encoding is lossy, but non-overlay upper image must be intact.
        assert np.mean(np.abs(a[30:85].astype(float)-before[30:85].astype(float))) < 9
    original.release()


def test_invalid_temporal_reference_is_not_silently_accepted(tmp_path):
    video=tmp_path/"source.mp4"
    _fixture(video)
    plan=_plan(video)
    plan["regions"][0]["reference_frames"]=[8,21]  # inside the overlay
    with pytest.raises(TemporalPlanError):
        TemporalCleanPlate(video,plan["regions"],10,320,180,24)


def test_exemplar_region_never_modifies_outside_approved_box(tmp_path):
    video=tmp_path/"source.mp4"
    _fixture(video)
    frame=cv2.VideoCapture(str(video))
    ok,src=frame.read()
    frame.release()
    assert ok
    item={"start":0.0,"end":2.4,"source":"exemplar-patch","kind":"logo",
          "box":[4,4,44,24],"donor_box":[94,4,134,24],"feather":3}
    comp=TemporalCleanPlate(video,[item],10,320,180,24)
    out=comp.apply(src,0)
    assert not np.array_equal(out[8:21,10:40],src[8:21,10:40])
    assert np.array_equal(out[40:, :],src[40:, :])
    assert np.array_equal(out[:, 160:],src[:,160:])


def test_clean_plate_preroll_avoids_jump_before_first_caption(tmp_path):
    source=tmp_path/"preroll.mp4"
    _fixture(source)
    plan=_plan(source)
    cleaner=TemporalCleanPlate(source,plan["regions"],10,320,180,24)
    cap=cv2.VideoCapture(str(source))
    frames=[]
    for _ in range(8):
        ok,f=cap.read()
        assert ok
        frames.append(f)
    cap.release()
    restored=[cleaner.apply(f,i) for i,f in enumerate(frames)]
    # The effect must already be prepared before frame 5 (first visible glyph).
    # It should not introduce a one-frame edit cut when the caption appears.
    diffs=[float(np.mean(np.abs(restored[i][120:160,20:250].astype(float)-
                                restored[i-1][120:160,20:250].astype(float))))
           for i in range(2,8)]
    assert max(diffs) < 30, diffs
    assert np.array_equal(restored[2],frames[2])  # before approved interval
