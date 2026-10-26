"""Standalone real LaMa TorchScript CPU backend for reviewed subtitle windows.

No VSR installation or GPU required; user supplies an Apache-2.0 LaMa model
checkpoint. Restores only the spatial/temporal rectangles explicitly reviewed.
No claim of reliable background restoration without visual inspection.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import tempfile

import cv2
import numpy as np


class LamaCPUError(RuntimeError):
    pass


# Known SHA-256 of signature-ai/big-lama/big-lama.pt (Apache-2.0).
REFERENCE_SHA256 = "344c77bbcb158f17dd143070d1e789f38a66c04202311ae3a258ef66667a9ea9"


def _validate_regions(regions, fps, width, height, total_frames):
    spans=[]
    for region in regions:
        if region.get("source")!="neural-window":
            continue
        a=int(round(float(region["start"])*fps))
        b=int(round(float(region["end"])*fps))
        if not (0<=a<b<=total_frames):
            raise LamaCPUError("invalid LaMa frame interval")
        boxes=region.get("boxes") or [region["box"]]
        for x1,y1,x2,y2 in boxes:
            if not (0<=x1<x2<=width and 0<=y1<y2<=height):
                raise LamaCPUError("invalid LaMa mask box")
        spans.append((a,b,boxes))
    spans.sort()
    if not spans or any(x[1]>y[0] for x,y in zip(spans,spans[1:])):
        raise LamaCPUError("specify non-overlapping reviewed neural windows")
    return spans


def _pad_to_eight(image, mask):
    h,w=image.shape[:2]
    ph=(-h)%8; pw=(-w)%8
    return (np.pad(image,((0,ph),(0,pw),(0,0)),mode="symmetric"),
            np.pad(mask,((0,ph),(0,pw)),mode="constant"))


def render_lama_cpu(video, output, *, model_path, regions, ffmpeg="ffmpeg",
                    threads=4, feather=1.5, vertical_context=150,
                    verify_sha256=None):
    """Process every decoded frame, including frames outside reviewed windows.

    Deliberately fail closed on missing model, frame loss or wrong timings.
    Video-only H264 output; VietDub final renderer handles dubbed audio.
    """
    import torch
    src,dst=Path(video).resolve(),Path(output).resolve()
    weight=Path(model_path).expanduser().resolve()
    if src==dst or not src.is_file():
        raise LamaCPUError("cannot overwrite input")
    if not weight.is_file():
        raise LamaCPUError(f"LaMa checkpoint missing: {weight}")
    if verify_sha256:
        digest=hashlib.sha256(weight.read_bytes()).hexdigest()
        if digest.lower()!=verify_sha256.lower():
            raise LamaCPUError("LaMa checkpoint checksum mismatch")
    cap=cv2.VideoCapture(str(src))
    if not cap.isOpened():
        raise LamaCPUError("cannot decode source video")
    width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps=float(cap.get(cv2.CAP_PROP_FPS))
    total_frames=int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if not (width>0 and height>0 and fps>0 and total_frames>0):
        cap.release();raise LamaCPUError("invalid dimensions/framerate")
    spans=_validate_regions(regions,fps,width,height,total_frames)
    torch.set_num_threads(max(1,min(16,int(threads))))
    model=torch.jit.load(str(weight),map_location="cpu").eval()
    dst.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix=".vietdub-lama-",suffix=".mp4",dir=dst.parent)
    os.close(fd)
    temp=Path(name)
    cmd=[ffmpeg,"-nostdin","-loglevel","error","-y",
         "-f","rawvideo","-pix_fmt","bgr24","-s",f"{width}x{height}",
         "-r",f"{fps:.8f}","-i","pipe:0","-an",
         "-c:v","libx264","-crf","18","-preset","fast",
         "-pix_fmt","yuv420p",str(temp)]
    process=subprocess.Popen(cmd,stdin=subprocess.PIPE,stderr=subprocess.PIPE)
    index=0
    try:
        for frame_i in range(total_frames):
            ok,frame=cap.read()
            if not ok:
                raise LamaCPUError(f"source prematurely ended at frame {frame_i}")
            while index<len(spans) and frame_i>=spans[index][1]:
                index+=1
            if index<len(spans) and spans[index][0]<=frame_i<spans[index][1]:
                boxes=spans[index][2]
                mask=np.zeros((height,width),np.float32)
                for x1,y1,x2,y2 in boxes:
                    mask[int(y1):int(y2),int(x1):int(x2)]=1.
                top=max(0,min(int(b[1]) for b in boxes)-int(vertical_context))
                bottom=min(height,max(int(b[3]) for b in boxes)+8)
                crop=frame[top:bottom]
                local_mask=mask[top:bottom]
                rgb=cv2.cvtColor(crop,cv2.COLOR_BGR2RGB).astype(np.float32)/255.
                img_pad,mask_pad=_pad_to_eight(rgb,local_mask)
                img=torch.from_numpy(np.ascontiguousarray(img_pad.transpose(2,0,1)))[None]
                m=torch.from_numpy(mask_pad[None,None])
                with torch.inference_mode():
                    result=model(img,m)[0].permute(1,2,0).cpu().numpy()
                patch=(np.clip(result[:crop.shape[0],:width],0,1)*255).astype(np.uint8)
                patch=cv2.cvtColor(patch,cv2.COLOR_RGB2BGR)
                alpha=cv2.GaussianBlur(local_mask,(0,0),float(feather))
                restored=np.clip(crop.astype(np.float32)*(1-alpha[:,:,None])+
                                 patch.astype(np.float32)*alpha[:,:,None],
                                 0,255).astype(np.uint8)
                frame[top:bottom]=restored
            process.stdin.write(frame.tobytes())
        process.stdin.close()
        stderr=process.stderr.read()
        if process.wait()!=0:
            raise LamaCPUError("FFmpeg: "+stderr.decode(errors="replace")[-800:])
        audit=cv2.VideoCapture(str(temp))
        decoded=0
        while audit.grab():decoded+=1
        audit.release()
        if decoded!=total_frames:
            raise LamaCPUError(f"encoder frame loss: {decoded}/{total_frames}")
        os.replace(temp,dst)
        return dst
    finally:
        cap.release()
        if process.poll() is None:
            process.kill();process.wait()
        temp.unlink(missing_ok=True)
