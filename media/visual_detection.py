"""Multi-pass OCR suggestions for a single user-selected preview frame.

Accuracy: compare native, enlarged and contrast-enhanced predictions, then
merge duplicate boxes. This NEVER automatically blurs anything; the user
must approve the exact time and rectangle.
"""
from __future__ import annotations

import cv2
import numpy as np


def _clip_box(box, width, height):
    x1, y1, x2, y2 = [int(round(float(x))) for x in box]
    return (max(0,min(width,x1)), max(0,min(height,y1)),
            max(0,min(width,x2)), max(0,min(height,y2)))


def _iou(a, b):
    iw=max(0,min(a[2],b[2])-max(a[0],b[0]))
    ih=max(0,min(a[3],b[3])-max(a[1],b[1]))
    shared=iw*ih
    aa=(a[2]-a[0])*(a[3]-a[1])
    bb=(b[2]-b[0])*(b[3]-b[1])
    return shared/max(1,aa+bb-shared)


def detect_frame_candidates(frame, detector, *, min_score=.35,
                            max_edge=1600, include_contrast=True):
    """Return (rectangle, confidence) candidates in original coordinates.

    The detector is a .detect(BGR) backend, such as PaddleDetector.
    Upscaled pass is skipped on high-res sources to bound memory.
    """
    if frame is None or len(frame.shape)!=3 or frame.shape[2]!=3:
        raise ValueError("Expected 3-channel BGR frame")
    height,width=frame.shape[:2]
    if height<2 or width<2:
        raise ValueError("Invalid frame dimensions")
    if not 0<=min_score<=1:
        raise ValueError("min_score must be 0..1")
    passes=[(frame,1.)]
    if max(width,height)<=max_edge/2:
        enlarged=cv2.resize(frame,None,fx=2.,fy=2.,
                            interpolation=cv2.INTER_CUBIC)
        passes.append((enlarged,2.))
    if include_contrast:
        lab=cv2.cvtColor(frame,cv2.COLOR_BGR2LAB)
        l,a,b=cv2.split(lab)
        l=cv2.createCLAHE(clipLimit=2.,tileGridSize=(8,8)).apply(l)
        enhanced=cv2.cvtColor(cv2.merge([l,a,b]),cv2.COLOR_LAB2BGR)
        passes.append((enhanced,1.))
    candidates=[]
    for img,scale in passes:
        for raw,score in detector.detect(img):
            confidence=float(score)
            if not np.isfinite(confidence) or confidence<min_score:
                continue
            try:
                box=_clip_box([float(v)/scale for v in raw],width,height)
            except (TypeError,ValueError,OverflowError):
                continue
            if box[2]-box[0]>=3 and box[3]-box[1]>=3:
                candidates.append((box,confidence))
    candidates.sort(key=lambda x:-x[1])
    merged=[]
    for box,score in candidates:
        match=None
        for index,(existing,old_score) in enumerate(merged):
            if _iou(box,existing)>=.45:
                match=index
                break
        if match is None:
            merged.append((box,score))
        else:
            existing,old_score=merged[match]
            union=(
                min(box[0],existing[0]),min(box[1],existing[1]),
                max(box[2],existing[2]),max(box[3],existing[3]))
            merged[match]=(union,max(old_score,score))
    return sorted(merged,key=lambda p:(p[0][1],p[0][0]))
