"""Hybrid integration: real FFmpeg CV stage, mocked LaMa call boundary.

Actual pretrained LaMa inference and real film output are evaluated separately.
"""
import shutil
from pathlib import Path

import pytest

cv2=pytest.importorskip("cv2")
np=pytest.importorskip("numpy")
from media import visual_hybrid


def sample_video(path):
    writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*"mp4v"),10,(320,180))
    assert writer.isOpened()
    for i in range(15):
        frame=np.zeros((180,320,3),np.uint8)
        frame[:]=(110,160,200)
        frame[115:]=(220,200,180)
        cv2.putText(frame,"HELLO",(70,145),cv2.FONT_HERSHEY_SIMPLEX,
                    .75,(255,255,255),2)
        writer.write(frame)
    writer.release()


@pytest.mark.skipif(not shutil.which("ffmpeg"),reason="requires FFmpeg")
def test_hybrid_composes_true_cv_video_before_neural_stage(tmp_path,monkeypatch):
    source=tmp_path/"original.mp4"
    sample_video(source)
    plan={"version":1,"source":str(source.resolve()),"width":320,
          "height":180,"fps":10,"frames":15,
          "regions":[
              {"source":"flat-strip-repaint","kind":"subtitle",
               "start":0,"end":1.5,"box":[0,115,320,162],
               "donor_rows":[165,177],"feather":1.3},
              {"source":"neural-window","kind":"logo",
               "start":0,"end":1.5,"box":[8,8,40,29]}
          ]}
    observed={}
    def stub_model(video,out,*,model_path,regions,ffmpeg):
        observed["input"]=str(video)
        observed["regions"]=regions
        observed["model_path"]=model_path
        import shutil
        shutil.copyfile(video,out)
        return Path(out)
    monkeypatch.setattr(visual_hybrid,"render_lama_cpu",stub_model)
    result=visual_hybrid.render_reviewed_hybrid(
        source,tmp_path/"result.mp4",plan,model_path="checkpoints/model.pt")
    assert result.is_file()
    assert len(observed["regions"])==1
    assert observed["regions"][0]["source"]=="neural-window"
    assert observed["input"]!=str(source)
    cap=cv2.VideoCapture(str(result))
    assert int(cap.get(cv2.CAP_PROP_FRAME_COUNT))==15
    cap.release()


def test_hybrid_rejects_source_mismatch_before_touching_video(tmp_path):
    source=tmp_path/"original.mp4"
    sample_video(source)
    with pytest.raises(ValueError,match="source/version"):
        visual_hybrid.render_reviewed_hybrid(
            source,tmp_path/"result.mp4",
            {"version":1,"source":"/wrong/path","regions":[]},
            model_path="model.pt")


def test_hybrid_fails_unknown_region_types(tmp_path):
    source=tmp_path/"original.mp4"
    sample_video(source)
    with pytest.raises(ValueError,match="unsupported"):
        visual_hybrid.render_reviewed_hybrid(
            source,tmp_path/"result.mp4",
            {"version":1,"source":str(source.resolve()),
             "regions":[{"source":"unvalidated-ai-magic","box":[1,2,3,4]}]},
            model_path="model.pt")
