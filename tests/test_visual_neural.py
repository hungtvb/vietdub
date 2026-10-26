"""VSR command adapter checks. Does NOT test neural model weights/inpainting."""
from pathlib import Path

import pytest

cv2=pytest.importorskip("cv2")
np=pytest.importorskip("numpy")

from media.visual_neural import (
    NeuralCleanupError,build_command,run_vsr
)


def _video(path, count=20):
    writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*"mp4v"),10,(160,96))
    assert writer.isOpened()
    for i in range(count):
        f=np.full((96,160,3),(40+i,80,130),dtype=np.uint8)
        writer.write(f)
    writer.release()


def _stub_root(path, *, drop_last=False):
    root=path/"vsr"
    (root/"backend").mkdir(parents=True)
    script=(
        "import sys,cv2,shutil\n"
        "source=sys.argv[sys.argv.index('-i')+1]\n"
        "target=sys.argv[sys.argv.index('-o')+1]\n"
        "if not "+str(drop_last)+":\n"
        "    shutil.copyfile(source,target)\n"
        "else:\n"
        "    cap=cv2.VideoCapture(source)\n"
        "    n=int(cap.get(cv2.CAP_PROP_FRAME_COUNT))\n"
        "    w=cv2.VideoWriter(target,cv2.VideoWriter_fourcc(*'mp4v'),10,(160,96))\n"
        "    for i in range(n-2):\n"
        "        ok,frame=cap.read()\n"
        "        if ok:w.write(frame)\n"
        "    cap.release();w.release()\n")
    (root/"backend"/"main.py").write_text(script,encoding="utf-8")
    return root


def test_neural_cli_uses_correct_ymin_ymax_xmin_xmax(tmp_path):
    root=_stub_root(tmp_path)
    cwd,cmd=build_command(root,tmp_path/"video.mp4",tmp_path/"out.mp4",
                          mode="sttn-det",areas=[(30,80,180,115)])
    assert cwd==root.resolve()
    assert cmd[-5:]==["-c","80","115","30","180"]


def test_neural_adapter_accepts_full_length_mock_output(tmp_path):
    root=_stub_root(tmp_path)
    source=tmp_path/"video.mp4"; _video(source)
    out=tmp_path/"clean.mp4"
    result=run_vsr(root,source,out,mode="sttn-det")
    assert result==out and out.is_file()
    cap=cv2.VideoCapture(str(out))
    assert int(cap.get(cv2.CAP_PROP_FRAME_COUNT))==20
    cap.release()


def test_neural_adapter_rejects_dropped_frames(tmp_path):
    root=_stub_root(tmp_path,drop_last=True)
    source=tmp_path/"video.mp4";_video(source)
    out=tmp_path/"clean.mp4"
    with pytest.raises(NeuralCleanupError,match="frames"):
        run_vsr(root,source,out,mode="lama")
    assert not out.exists()


def test_neural_models_are_not_silently_faked(tmp_path):
    source=tmp_path/"video.mp4"; _video(source)
    with pytest.raises(NeuralCleanupError,match="not found"):
        run_vsr(tmp_path/"not-installed",source,tmp_path/"out.mp4")
    root=_stub_root(tmp_path)
    with pytest.raises(NeuralCleanupError,match="Unsupported"):
        build_command(root,source,tmp_path/"out.mp4",mode="made-up")
