"""Motion-compensated clean-plate compositing for *reviewed* video overlays.

Use ONLY when an operator has marked a complete overlay rectangle, its visible
time interval, and clean source frames on both sides of that interval. It cannot
magically recover a scene hidden in every source frame. Never infer clean-plate
mode from ordinary OCR confidence alone.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


class TemporalPlanError(ValueError):
    pass


def is_temporal_region(region):
    return region.get("source") in ("temporal-clean-plate", "exemplar-patch")


def _xyxy(box, w, h):
    if len(box) != 4:
        raise TemporalPlanError("box must have exactly four coordinates")
    x1, y1, x2, y2 = map(int, box)
    if not (0 <= x1 < x2 <= w and 0 <= y1 < y2 <= h):
        raise TemporalPlanError("invalid overlay coordinates")
    return x1, y1, x2, y2


def _smoothstep(value):
    x = max(0.0, min(1.0, value))
    return x*x*(3.0-2.0*x)


@dataclass
class Prepared:
    region: dict
    box: tuple[int, int, int, int]
    alpha: np.ndarray
    reference_frames: tuple[np.ndarray, ...] = ()
    gray_refs: tuple[np.ndarray, ...] = ()
    flow_height: int = 0
    blend_frames: tuple[int, int] = (0, 0)
    donor_box: tuple[int, int, int, int] | None = None


class TemporalCleanPlate:
    """Apply reviewable manual overlay annotations to decoded source frames.

    The output video renderer supplies frames in normal chronological order.
    This engine does not automatically classify every caption as removable.
    """

    def __init__(self, video, regions, fps, width, height, frame_count):
        self.fps, self.w, self.h = float(fps), int(width), int(height)
        self.frame_count = int(frame_count)
        self.items = []
        cap = cv2.VideoCapture(str(video))
        if not cap.isOpened():
            raise TemporalPlanError("cannot open video for clean-plate references")
        try:
            for r in regions:
                if not is_temporal_region(r):
                    continue
                box = _xyxy(r["box"], self.w, self.h)
                x1, y1, x2, y2 = box
                if r["source"] == "exemplar-patch":
                    donor = _xyxy(r.get("donor_box", ()), self.w, self.h)
                    if (donor[2]-donor[0], donor[3]-donor[1]) != (x2-x1, y2-y1):
                        raise TemporalPlanError("donor and destination sizes differ")
                    border = min(16, max(2, int(r.get("feather", 7))))
                    alpha = np.ones((y2-y1, x2-x1), np.float32)
                    alpha[:border] = 0; alpha[-border:] = 0
                    alpha[:, :border] = 0; alpha[:, -border:] = 0
                    alpha = cv2.GaussianBlur(alpha, (0, 0), max(1, border/3))
                    self.items.append(Prepared(r, box, alpha, donor_box=donor))
                    continue
                indices = r.get("reference_frames")
                if not isinstance(indices, list) or len(indices) != 2:
                    raise TemporalPlanError("temporal overlay requires two approved reference_frames")
                a, b = map(int, indices)
                first_frame = max(0, int(round(float(r["start"])*self.fps)))
                last_frame = int(round(float(r["end"])*self.fps))
                if not (0 <= a < first_frame < last_frame <= b < self.frame_count):
                    raise TemporalPlanError(
                        "clean reference frames must fall strictly before/after overlay")
                flow_height = int(r.get("flow_height", y1-2))
                if not 40 <= flow_height <= y1:
                    raise TemporalPlanError("flow_height must lie above overlay and >=40")
                refs = []
                for idx in (a, b):
                    cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                    ok, frame = cap.read()
                    if not ok or frame.shape[:2] != (self.h, self.w):
                        raise TemporalPlanError("cannot decode clean reference frame")
                    refs.append(frame)
                blend = tuple(map(int, r.get("blend_frames", [
                    round(first_frame+(last_frame-first_frame)*.35),
                    round(first_frame+(last_frame-first_frame)*.65)
                ])))
                if len(blend) != 2 or not first_frame <= blend[0] < blend[1] <= last_frame:
                    raise TemporalPlanError("invalid clean-reference blend_frames")
                alpha = np.zeros((self.h, self.w), np.float32)
                alpha[y1:y2, x1:x2] = 1
                alpha = cv2.GaussianBlur(alpha, (0, 0), float(r.get("feather", 2.5)))
                # Keep only a narrow padded ROI in memory, not float32 4K frames.
                margin = min(20, max(3, int(4*float(r.get("feather", 2.5)))))
                ox1, oy1 = max(0, x1-margin), max(0, y1-margin)
                ox2, oy2 = min(self.w, x2+margin), min(self.h, y2+margin)
                adjusted = {**r, "_effective_box":(ox1,oy1,ox2,oy2)}
                self.items.append(Prepared(
                    adjusted, box, alpha[oy1:oy2,ox1:ox2],
                    reference_frames=tuple(refs),
                    gray_refs=tuple(cv2.cvtColor(fr[:flow_height],cv2.COLOR_BGR2GRAY) for fr in refs),
                    flow_height=flow_height, blend_frames=blend))
        finally:
            cap.release()

    def _warp_ref(self, src, prepared, index):
        x1,y1,x2,y2 = prepared.region["_effective_box"]
        cropped_height = prepared.flow_height
        dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
        current_gray = cv2.cvtColor(src[:cropped_height], cv2.COLOR_BGR2GRAY)
        flow = dis.calc(current_gray, prepared.gray_refs[index], None)
        ys, xs = np.mgrid[y1:y2, x1:x2]
        f = flow[np.minimum(ys, cropped_height-1), xs]
        map_x = xs.astype(np.float32)+f[:,:,0]
        map_y = ys.astype(np.float32)+f[:,:,1]
        return cv2.remap(prepared.reference_frames[index],map_x,map_y,
                         cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT)

    def apply(self, frame, frame_index):
        """Return a new frame. Only manually approved overlay pixels are changed."""
        n = int(frame_index)
        out = frame.copy()
        for p in self.items:
            r = p.region
            if not (float(r["start"])*self.fps <= n < float(r["end"])*self.fps):
                continue
            if r["source"] == "exemplar-patch":
                x1,y1,x2,y2=p.box
                a,b,c,d=p.donor_box
                donor=frame[b:d,a:c].astype(np.float32)
                old=out[y1:y2,x1:x2].astype(np.float32)
                mixed=old*(1-p.alpha[:,:,None])+donor*p.alpha[:,:,None]
                out[y1:y2,x1:x2]=np.clip(mixed,0,255).astype(np.uint8)
                continue
            x1,y1,x2,y2=p.region["_effective_box"]
            n1,n2=p.blend_frames
            weight=_smoothstep((n-n1)/(n2-n1))
            if weight<=0:
                plate=self._warp_ref(frame,p,0)
            elif weight>=1:
                plate=self._warp_ref(frame,p,1)
            else:
                plate1=self._warp_ref(frame,p,0).astype(np.float32)
                plate2=self._warp_ref(frame,p,1).astype(np.float32)
                plate=np.clip(plate1*(1-weight)+plate2*weight,0,255).astype(np.uint8)
            original=out[y1:y2,x1:x2]
            mixed=np.clip(original.astype(np.float32)*(1-p.alpha[:,:,None])+
                          plate.astype(np.float32)*p.alpha[:,:,None],0,255).astype(np.uint8)
            out[y1:y2,x1:x2]=np.where(p.alpha[:,:,None]>=.0005,mixed,original)
        return out
