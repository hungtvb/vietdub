"""Optional color-guided mask for operator-approved expanding flat graphics.

Use only with a reviewed rectangle and a review-specific HSV color range.
It is not a generic text detector. A mask that is narrower than the actual
graphic will leave readable text: check the OUTPUT frame-by-frame.
"""
from __future__ import annotations


def expanding_graphic_mask(frame, box, *, hue_min=90, hue_max=158,
                           saturation_min=55, brightness_min=75,
                           blue_fraction=.12, padding=15, min_width=73,
                           row_start=.14, row_end=.90, feather=2.4):
    """Return full-frame float32 alpha covering visible left-anchored graphic.

    Width is inferred per source frame, not hardcoded at max extent.
    All parameters should come from operator review, not arbitrary scene OCR.
    """
    import cv2
    import numpy as np
    height,width=frame.shape[:2]
    x1,y1,x2,y2=map(int,box)
    if not (0<=x1<x2<=width and 0<=y1<y2<=height):
        raise ValueError("invalid reviewed overlay box")
    if not (0<=hue_min<=hue_max<=179 and 0<=saturation_min<=255
            and 0<=brightness_min<=255 and 0<blue_fraction<1
            and 0<=row_start<row_end<=1 and 0<min_width<=x2-x1
            and padding>=0 and feather>=0):
        raise ValueError("invalid reviewed HSV mask parameters")
    sy=y1+round((y2-y1)*row_start)
    ey=y1+round((y2-y1)*row_end)
    ey=max(sy+1,min(y2,ey))
    hsv=cv2.cvtColor(frame[sy:ey,x1:x2],cv2.COLOR_BGR2HSV)
    valid=((hsv[:,:,0]>=hue_min)&(hsv[:,:,0]<=hue_max)
           &(hsv[:,:,1]>=saturation_min)&(hsv[:,:,2]>=brightness_min))
    fraction=np.mean(valid,axis=0)
    positive=np.flatnonzero(fraction>blue_fraction)
    extent=(int(positive.max())+1+int(padding)) if positive.size else int(min_width)
    extent=max(int(min_width),min(x2-x1,extent))
    mask=np.zeros((height,width),np.float32)
    mask[y1:y2,x1:x1+extent]=1.
    if feather>0:
        mask=cv2.GaussianBlur(mask,(0,0),float(feather))
    return mask
