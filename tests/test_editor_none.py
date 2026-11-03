"""No-subtitle editor export must never publish a surprise SRT sidecar."""
import shutil
import wave

import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

from media.editor import export_edit


@pytest.mark.skipif(not shutil.which("ffmpeg"),reason="ffmpeg unavailable")
def test_editor_none_renders_video_without_srt(tmp_path):
    video=tmp_path/"source.mp4"
    writer=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*"mp4v"),10,(160,96))
    assert writer.isOpened()
    for i in range(12):
        frame=np.full((96,160,3),(i*5,70,110),np.uint8)
        writer.write(frame)
    writer.release()
    audio=tmp_path/"mix.wav"
    with wave.open(str(audio),"wb") as wf:
        wf.setnchannels(1);wf.setsampwidth(2);wf.setframerate(16000)
        wf.writeframes(np.zeros(16000*2,dtype=np.int16).tobytes())
    result=export_edit(video,audio,[],tmp_path/"none.mp4",0,1,
                       sub_mode="none")
    assert result.is_file() and result.stat().st_size > 500
    assert not result.with_suffix(".srt").exists()
    assert not list(tmp_path.glob(".vietdub-*.srt"))
