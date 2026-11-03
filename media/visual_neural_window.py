"""Frame-limited neural inpainting for *reviewed* subtitle windows.

This adapter prevents upstream STTN/LaMa/ProPainter from touching unrelated
shots, faces, logos or credits. It cannot replace model inference: a real
installed model/weights are required. It enforces per-frame temporal masks.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile

import cv2
import numpy as np

from media.visual_neural import run_vsr, NeuralCleanupError


def _mask(height, width, boxes, feather):
    mask=np.zeros((height,width),np.float32)
    for box in boxes:
        x1,y1,x2,y2=map(int,box)
        if not (0<=x1<x2<=width and 0<=y1<y2<=height):
            raise NeuralCleanupError("Invalid reviewed box")
        mask[y1:y2,x1:x2]=1.
    if feather>0:
        mask=cv2.GaussianBlur(mask,(0,0),float(feather))
    return mask[:,:,None]


def run_windowed_vsr(vsr_root, source, output, *, regions, mode="sttn-auto",
                     python_exe=None, ffmpeg="ffmpeg", feather=2.,
                     timeout_seconds=7200):
    """Neural-inpaint only reviewed [start,end) regions; never whole frames.

    All windows must be sorted and non-overlapping and use a constant FPS
    source (VFR needs an explicit preprocessing step). The original video
    is never overwritten and audio is intentionally deferred to final render.
    """
    src,dst=Path(source).resolve(),Path(output).resolve()
    if src==dst or not src.is_file():
        raise NeuralCleanupError("Cannot overwrite source")
    cap=cv2.VideoCapture(str(src))
    if not cap.isOpened():
        raise NeuralCleanupError("Cannot decode source")
    fps=float(cap.get(cv2.CAP_PROP_FPS))
    n=int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    w,h=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if not fps>0 or not n>0:
        cap.release()
        raise NeuralCleanupError("Missing frame rate/count")
    items=[]
    for region in regions:
        start=int(round(float(region["start"])*fps))
        end=int(round(float(region["end"])*fps))
        if not 0<=start<end<=n:
            cap.release()
            raise NeuralCleanupError("Neural review interval out of bounds")
        boxes=region.get("boxes") or [region["box"]]
        if not boxes:
            cap.release()
            raise NeuralCleanupError("Neural window must specify spatial boxes")
        items.append((start,end,boxes,_mask(h,w,boxes,feather)))
    items.sort(key=lambda x:x[0])
    if not items or any(a[1]>b[0] for a,b in zip(items,items[1:])):
        cap.release()
        raise NeuralCleanupError("Specify non-overlapping reviewed neural windows")

    dst.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vietdub-neural-") as scratch:
        scratch=Path(scratch)
        restored=[]
        try:
            for k,(start,end,boxes,alpha) in enumerate(items):
                part=scratch/f"input_{k}.mp4"
                writer=cv2.VideoWriter(str(part),cv2.VideoWriter_fourcc(*"mp4v"),
                                       fps,(w,h))
                if not writer.isOpened():
                    raise NeuralCleanupError("Cannot encode neural input clip")
                cap.set(cv2.CAP_PROP_POS_FRAMES,start)
                try:
                    for i in range(start,end):
                        ok,frame=cap.read()
                        if not ok:raise NeuralCleanupError("Source has truncated window")
                        writer.write(frame)
                finally:
                    writer.release()
                target=scratch/f"restored_{k}.mp4"
                run_vsr(vsr_root,part,target,mode=mode,areas=boxes,
                        python_exe=python_exe,timeout_seconds=timeout_seconds)
                restored.append(cv2.VideoCapture(str(target)))
                if not restored[-1].isOpened():
                    raise NeuralCleanupError("Cannot decode neural restored window")
            # ffmpeg rawvideo is streamable and preserves exact frame count.
            temp=scratch/"composited.mp4"
            cmd=[ffmpeg,"-nostdin","-loglevel","error","-y",
                 "-f","rawvideo","-pix_fmt","bgr24","-s",f"{w}x{h}",
                 "-r",str(fps),"-i","pipe:0","-an",
                 "-c:v","libx264","-crf","18","-pix_fmt","yuv420p",str(temp)]
            process=subprocess.Popen(cmd,stdin=subprocess.PIPE,stderr=subprocess.PIPE)
            idx=0
            cap.set(cv2.CAP_PROP_POS_FRAMES,0)
            try:
                for i in range(n):
                    ok,frame=cap.read()
                    if not ok:raise NeuralCleanupError(f"Source truncated at {i}/{n}")
                    while idx<len(items) and i>=items[idx][1]:
                        idx+=1
                    if idx<len(items) and items[idx][0]<=i<items[idx][1]:
                        ok,generated=restored[idx].read()
                        if not ok:raise NeuralCleanupError("Neural window truncated")
                        alpha=items[idx][3]
                        # Composite in the reviewed mask only, even when the
                        # upstream model alters outside it.
                        frame=np.clip(
                            frame.astype(np.float32)*(1-alpha)+
                            generated.astype(np.float32)*alpha,0,255).astype(np.uint8)
                    process.stdin.write(frame.tobytes())
                process.stdin.close()
                error=process.stderr.read()
                if process.wait()!=0:
                    raise NeuralCleanupError("FFmpeg: "+error.decode(errors="replace")[-700:])
            finally:
                if process.poll() is None:
                    process.kill();process.wait()
            # Decode each frame, not container header only.
            chk=cv2.VideoCapture(str(temp))
            ct=0
            while chk.grab():ct+=1
            chk.release()
            if ct!=n:
                raise NeuralCleanupError(f"Window compositing dropped frames {ct}/{n}")
            os.replace(temp,dst)
            return dst
        finally:
            cap.release()
            for reader in restored:reader.release()
