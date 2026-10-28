"""Conservative user-approved template tracking for moving subtitle/logo masks.

Tracks are computed BEFORE any output is published. A failed match, probable
scene cut or forward/backward drift stops rendering. Explicit user keyframes
re-anchor the tracker; no silent fallback to a stationary or face mask.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


class TrackingError(ValueError):
    pass


@dataclass(frozen=True)
class TrackPoint:
    box: tuple[int, int, int, int]
    confidence: float
    source: str  # keyframe | template


def _scene_jump(previous, current):
    def hist(frame):
        resized = cv2.resize(frame, (120, 68))
        hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)
        values = cv2.calcHist([hsv], [0, 1], None, [20, 12],
                              [0, 180, 0, 256])
        return cv2.normalize(values, values)
    histogram_distance = float(cv2.compareHist(
        hist(previous), hist(current), cv2.HISTCMP_BHATTACHARYYA))
    # HSV histograms can look similar after a hard lighting/color cut.
    # Pixel-wise differences on a small image catch those edits. Using
    # conservative MAX means ambiguous cuts require a human keyframe.
    a = cv2.resize(previous, (120, 68)).astype(np.int16)
    b = cv2.resize(current, (120, 68)).astype(np.int16)
    pixel_distance = float(np.mean(np.abs(a-b))) / 130.0
    return max(histogram_distance, pixel_distance)


def _match(previous, current, box, *, max_motion, min_confidence):
    height, width = previous.shape[:2]
    x1, y1, x2, y2 = box
    span_x, span_y = x2-x1, y2-y1
    if min(span_x, span_y) < 6:
        raise TrackingError("Tracking ROI smaller than 6 pixels")
    template = cv2.cvtColor(previous[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    if float(template.std()) < 7.0:
        raise TrackingError(
            "Tracking ROI has too little detail; add a manual keyframe")
    pad = max(6, int(max_motion))
    left, top = max(0, x1-pad), max(0, y1-pad)
    right, bottom = min(width, x2+pad), min(height, y2+pad)
    target = cv2.cvtColor(
        current[top:bottom, left:right], cv2.COLOR_BGR2GRAY)
    if target.shape[0] < span_y or target.shape[1] < span_x:
        raise TrackingError("Tracking search area too small")
    similarity = cv2.matchTemplate(
        target, template, cv2.TM_CCOEFF_NORMED)
    _, confidence, _, maximum = cv2.minMaxLoc(similarity)
    if not np.isfinite(confidence) or confidence < min_confidence:
        raise TrackingError(
            f"Tracking confidence {confidence:.3f} below "
            f"{min_confidence:.3f}; add a correction keyframe")
    nx, ny = left+maximum[0], top+maximum[1]
    return (nx, ny, nx+span_x, ny+span_y), float(confidence)


def _keyframes(region, start, end, shape):
    height, width = shape[:2]
    original = tuple(map(int, region["box"]))
    raw = region.get("keyframes") or [
        {"frame": start, "box": original}]
    points = {}
    for record in raw:
        frame = int(record["frame"])
        box = tuple(map(int, record["box"]))
        if frame < start or frame >= end or frame in points:
            raise TrackingError("Keyframe outside interval or duplicated")
        x1, y1, x2, y2 = box
        if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
            raise TrackingError("Keyframe rectangle outside video")
        if (x2-x1, y2-y1) != (
                original[2]-original[0], original[3]-original[1]):
            raise TrackingError(
                "Tracking keyframes must keep a constant rectangle size")
        points[frame] = box
    if start not in points:
        points[start] = original
    return points


def track_region(video, region, *, min_confidence=.68, max_motion=24,
                 scene_limit=.52, backward_tolerance=4):
    """Return every [start,end) frame's TrackPoint or fail the entire request.

    This is suitable for tracking a textured *moving logo*. A logo anchored to
    the screen is better handled with a static user region. The detector does
    not infer when a watermark appears/disappears; the user selects timing.
    """
    if not (.3 <= min_confidence <= 1 and 1 <= max_motion <= 200
            and 0 < scene_limit <= 1 and 0 <= backward_tolerance <= 20):
        raise TrackingError("Invalid tracking thresholds")
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise TrackingError(f"Cannot decode tracking video: {video}")
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if not fps > 0 or count < 1:
            raise TrackingError("Invalid tracking video metadata")
        first = round(float(region["start"])*fps)
        last = round(float(region["end"])*fps)
        if not 0 <= first < last <= count:
            raise TrackingError("Invalid tracking interval")
        cap.set(cv2.CAP_PROP_POS_FRAMES, first)
        ok, previous = cap.read()
        if not ok:
            raise TrackingError(f"Cannot decode frame {first}")
        anchors = _keyframes(region, first, last, previous.shape)
        box = anchors[first]
        result = {first: TrackPoint(box, 1.0, "keyframe")}
        for frame in range(first+1, last):
            ok, current = cap.read()
            if not ok:
                raise TrackingError(f"Cannot decode frame {frame}")
            if frame in anchors:
                box = anchors[frame]
                result[frame] = TrackPoint(box, 1.0, "keyframe")
            else:
                jump = _scene_jump(previous, current)
                if jump > scene_limit:
                    raise TrackingError(
                        f"Probable scene cut at frame {frame} "
                        f"(distance={jump:.3f}); split the reviewed interval")
                found, confidence = _match(
                    previous, current, box, max_motion=max_motion,
                    min_confidence=min_confidence)
                reverse, reverse_confidence = _match(
                    current, previous, found, max_motion=max_motion,
                    min_confidence=min_confidence)
                drift = max(abs(reverse[j]-box[j]) for j in range(4))
                if drift > backward_tolerance:
                    raise TrackingError(
                        f"Forward/backward drift at frame {frame} "
                        f"({drift} pixels); add a correction keyframe")
                box = found
                result[frame] = TrackPoint(
                    box, min(confidence, reverse_confidence), "template")
            previous = current
        return result
    finally:
        cap.release()
