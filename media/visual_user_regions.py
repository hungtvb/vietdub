"""User-directed visual cleanup regions and single-frame preview.

Manual regions always mask the EXACT reviewed rectangle; they must never pass
through OCR color thresholds that could leave shadowed lettering in place.
No PaddleOCR, FFmpeg, CUDA, or Qt are required to preview a manual region.
"""
from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np


class UserRegionError(ValueError):
    pass


MODES = ("blur", "pixelate", "inpaint")
KINDS = ("subtitle", "text", "logo")
SOURCE = "user"


def video_metadata(video):
    path = Path(video).expanduser().resolve()
    cap = cv2.VideoCapture(str(path))
    try:
        if not path.is_file() or not cap.isOpened():
            raise UserRegionError(f"Cannot open source video: {path}")
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if w < 2 or h < 2 or frames < 1 or not math.isfinite(fps) or fps <= 0:
            raise UserRegionError("Source video has invalid dimensions/FPS/frame count")
        return {
            "version": 1, "source": str(path), "width": w,
            "height": h, "fps": fps, "frames": frames
        }
    finally:
        cap.release()


def validate_region(region, width, height, duration):
    """Return sanitized manual region with exact dimensions and time bounds."""
    if region.get("source") != SOURCE:
        raise UserRegionError("Only explicit user regions can be edited here")
    box = region.get("box")
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        raise UserRegionError("A region requires [x1, y1, x2, y2]")
    try:
        coordinates = [int(v) for v in box]
        start, end = float(region["start"]), float(region["end"])
        strength = int(region.get("strength", 16))
        feather = float(region.get("feather", 2))
    except (TypeError, ValueError, KeyError, OverflowError) as exc:
        raise UserRegionError("Invalid region coordinates/time/strength") from exc
    x1, y1, x2, y2 = coordinates
    if not all(math.isfinite(v) for v in (start, end, feather)):
        raise UserRegionError("Non-finite region time/feather")
    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        raise UserRegionError("Region extends beyond source video")
    if not (0 <= start < end <= duration + 1e-3):
        raise UserRegionError("Start/end time is outside the source video")
    mode = str(region.get("mode", "blur"))
    kind = str(region.get("kind", "text"))
    if mode not in MODES or kind not in KINDS:
        raise UserRegionError("Invalid cleanup mode/category")
    if not (1 <= strength <= 64 and 0 <= feather <= 16):
        raise UserRegionError("Strength or edge feather outside safe limits")
    return {
        "start": start, "end": end, "box": coordinates,
        "kind": kind, "source": SOURCE,
        "mode": mode, "strength": strength, "feather": feather,
        "confidence": 1.0
    }


def validate_plan(plan, video):
    """Reject stale plans before rendering / previewing a new video source."""
    metadata = video_metadata(video)
    if (plan.get("version") != 1 or plan.get("source") != metadata["source"]
            or plan.get("width") != metadata["width"]
            or plan.get("height") != metadata["height"]
            or plan.get("frames") != metadata["frames"]
            or abs(float(plan.get("fps", 0)) - metadata["fps"]) > .02):
        raise UserRegionError("Region plan does not match this video; review again")
    duration = metadata["frames"] / metadata["fps"]
    regions = [
        validate_region(r, metadata["width"], metadata["height"], duration)
        for r in plan.get("regions", []) if r.get("source") == SOURCE
    ]
    return metadata, regions


def _effective_box(frame, region):
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = map(int, region["box"])
    if not (0 <= x1 < x2 <= w and 0 <= y1 < y2 <= h):
        raise UserRegionError("Region coordinates outside current frame")
    return x1, y1, x2, y2


def apply_user_regions(frame, regions, frame_number, fps):
    """Paint selected regions, frame-accurate and without touching outside pixels.

    A region's interval is [round(start*fps), round(end*fps)). Gaussian and
    mosaic operations work on a local padded crop, not full-size float frames.
    Edges are feathered within a <=16px border INSIDE the chosen rectangle.
    """
    if frame is None or frame.ndim != 3 or frame.shape[2] != 3:
        raise UserRegionError("Expected BGR color frame")
    if not fps > 0:
        raise UserRegionError("FPS must be positive")
    result = frame.copy()
    h, w = frame.shape[:2]
    duration = float("inf")  # source duration is checked when saving a plan
    for raw in regions:
        region = validate_region(raw, w, h, duration)
        first = int(round(region["start"] * fps))
        last = int(round(region["end"] * fps))
        if not (first <= frame_number < last):
            continue
        x1, y1, x2, y2 = _effective_box(result, region)
        strength = region["strength"]
        mode = region["mode"]
        feather = region["feather"]
        width, height = x2-x1, y2-y1
        if mode == "inpaint":
            mask = np.zeros((h, w), dtype=np.uint8)
            mask[y1:y2, x1:x2] = 255
            # Telea is local; this is deliberately a rectangular mask, not a
            # glyph-only OCR mask, so any translucent strip is covered.
            restored = cv2.inpaint(result, mask, min(9, max(2, strength//5)), cv2.INPAINT_TELEA)
            replacement = restored[y1:y2, x1:x2]
        elif mode == "blur":
            radius = max(2, strength)
            margin = min(3*radius, max(w, h))
            bx1, by1 = max(0, x1-margin), max(0, y1-margin)
            bx2, by2 = min(w, x2+margin), min(h, y2+margin)
            padded = result[by1:by2, bx1:bx2]
            blurred = cv2.GaussianBlur(padded, (0, 0), sigmaX=float(radius))
            replacement = blurred[y1-by1:y2-by1, x1-bx1:x2-bx1]
        else:  # mosaic / pixelation
            cell = max(2, strength)
            small = cv2.resize(result[y1:y2, x1:x2],
                               (max(1, width//cell), max(1, height//cell)),
                               interpolation=cv2.INTER_AREA)
            replacement = cv2.resize(small, (width, height),
                                     interpolation=cv2.INTER_NEAREST)
        if feather <= 0:
            result[y1:y2, x1:x2] = replacement
            continue
        # A softened rectangle, cropped locally. Outside stays bit-exact.
        alpha = np.ones((height, width), dtype=np.float32)
        edge = min(float(feather), width/2, height/2)
        if edge > 0:
            ys, xs = np.ogrid[:height, :width]
            distance = np.minimum(np.minimum(xs, width-1-xs),
                                  np.minimum(ys, height-1-ys)).astype(np.float32)
            alpha = np.clip(distance / edge, 0, 1)
        before = result[y1:y2, x1:x2].astype(np.float32)
        after = replacement.astype(np.float32)
        result[y1:y2, x1:x2] = np.clip(
            before * (1-alpha[..., None]) + after * alpha[..., None],
            0, 255).astype(np.uint8)
    return result
