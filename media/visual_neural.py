"""Opt-in neural video inpainting bridge (external local VSR installation).

This is a *backend adapter*, not a claim that VietDub implements STTN/LaMa/
ProPainter weights itself. The user installs Apache-2.0 VSR separately.
It is never invoked unless explicitly selected. Fail rather than degrading to
OpenCV blur if the model/runtime is unavailable.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


class NeuralCleanupError(RuntimeError):
    pass


MODES = ("sttn-det", "sttn-auto", "lama", "propainter")


def build_command(vsr_root, video, output, *, mode="sttn-det",
                  areas=(), python_exe=None):
    root = Path(vsr_root).expanduser().resolve()
    script = root / "backend" / "main.py"
    if not script.is_file():
        raise NeuralCleanupError(
            f"VSR backend/main.py not found in {root}; install upstream VSR separately")
    if mode not in MODES:
        raise NeuralCleanupError("Unsupported neural inpainting mode: "+str(mode))
    # Upstream STTN_AUTO skips detection; with no areas its CLI defaults to
    # the FULL VIDEO FRAME. Refuse to inpaint every pixel accidentally.
    if mode == "sttn-auto" and not areas:
        raise NeuralCleanupError("STTN auto requires at least one reviewed subtitle area")
    cmd = [str(python_exe or sys.executable), str(script),
           "-i", str(Path(video).resolve()), "-o", str(Path(output).resolve()),
           "--inpaint-mode", mode]
    for box in areas:
        if len(box) != 4:
            raise NeuralCleanupError("subtitle area must be xyxy")
        x1,y1,x2,y2 = map(int,box)
        if not (0 <= x1 < x2 and 0 <= y1 < y2):
            raise NeuralCleanupError("invalid subtitle bounding box")
        # Upstream VSR CLI expects ymin ymax xmin xmax (NOT xyxy).
        cmd += ["-c",str(y1),str(y2),str(x1),str(x2)]
    return root,cmd


def _count_frames(path):
    try:
        import cv2
    except ImportError as exc:
        raise NeuralCleanupError("Install OpenCV for frame validation") from exc
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise NeuralCleanupError(f"Invalid video: {path}")
    try:
        count = 0
        while cap.grab():
            count+=1
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        return count,fps
    finally:
        cap.release()


def run_vsr(vsr_root, video, output, *, mode="sttn-det", areas=(),
            python_exe=None, timeout_seconds=7200):
    src,dst = Path(video).resolve(),Path(output).resolve()
    if not src.is_file() or src == dst:
        raise NeuralCleanupError("Invalid input or output would overwrite source")
    dst.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix=".vietdub-vsr-",suffix=".mp4",dir=dst.parent)
    os.close(fd)
    temp=Path(name)
    try:
        root,cmd=build_command(vsr_root,src,temp,mode=mode,
                               areas=areas,python_exe=python_exe)
        try:
            done=subprocess.run(cmd,cwd=root,capture_output=True,text=True,
                                timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            raise NeuralCleanupError("VSR model processing timed out") from exc
        if done.returncode or not temp.is_file() or temp.stat().st_size==0:
            raise NeuralCleanupError("VSR failed: "+(done.stderr or done.stdout)[-1200:])
        old_count,old_fps=_count_frames(src)
        new_count,new_fps=_count_frames(temp)
        if old_count!=new_count or abs(old_fps-new_fps)>.03:
            raise NeuralCleanupError(
                f"VSR lost/repeated frames or changed fps: "
                f"source={old_count}@{old_fps:.4f}, output={new_count}@{new_fps:.4f}")
        os.replace(temp,dst)
        return dst
    finally:
        temp.unlink(missing_ok=True)
