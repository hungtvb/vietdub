"""Tiny traced TorchScript tests for CPU LaMa runtime; no 206MB model in Git.

CI without torch skips this module, but genuine pretrained checkpoint is
tested on actual Chinese footage separately.
"""
import shutil
import pytest

cv2=pytest.importorskip("cv2")
np=pytest.importorskip("numpy")
torch=pytest.importorskip("torch")

from media.visual_lama_cpu import render_lama_cpu,LamaCPUError


class SimpleInpaint(torch.nn.Module):
    def forward(self, image, mask):
        return image*(1-mask)+torch.ones_like(image)*mask


@pytest.mark.skipif(not shutil.which("ffmpeg"),reason="ffmpeg unavailable")
def test_cpu_model_affects_only_reviewed_time_and_pixels(tmp_path):
    model=torch.jit.trace(SimpleInpaint(),
        (torch.zeros((1,3,96,160)),torch.zeros((1,1,96,160))))
    model_path=tmp_path/"mock_model.pt"
    model.save(str(model_path))
    video=tmp_path/"source.mp4"
    writer=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*"mp4v"),10,(160,96))
    assert writer.isOpened()
    for i in range(12):
        frame=np.full((96,160,3),(70,90,130),np.uint8)
        writer.write(frame)
    writer.release()
    output=tmp_path/"after.mp4"
    result=render_lama_cpu(video,output,model_path=model_path,
        regions=[{"source":"neural-window","start":.3,"end":.8,
                  "box":[45,61,110,86]}],threads=2)
    assert result.is_file()
    before=cv2.VideoCapture(str(video))
    after=cv2.VideoCapture(str(output))
    for index in range(12):
        ok1,a=before.read();ok2,b=after.read()
        assert ok1 and ok2
        assert np.mean(np.abs(a[:45].astype(float)-b[:45].astype(float)))<8
        if 3<=index<8:
            assert b[72,75,2]>a[72,75,2]+50
        else:
            assert np.mean(np.abs(a.astype(float)-b.astype(float)))<9
    before.release();after.release()


def test_bad_reviewed_interval_is_rejected():
    from media.visual_lama_cpu import _validate_regions
    with pytest.raises(LamaCPUError):
        _validate_regions([{"source":"neural-window",
                             "start":1.0,"end":.2,"box":[0,0,10,10]}],
                          10,160,96,20)
