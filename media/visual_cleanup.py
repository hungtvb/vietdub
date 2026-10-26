"""VietDub opt-in visual cleanup: temporal OCR and conservative static overlays.

Analyze to reviewable JSON first; blur/inpaint second. Frame-based CFR video only.
No audio copied: VietDub's final render attaches the already-mixed dub.
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from media.visual_precise import pixel_mask, tight_box, refine_subtitle_bounds


class VisualCleanupError(RuntimeError):
    pass


@dataclass
class Region:
    start: float
    end: float
    box: tuple[int, int, int, int]
    kind: str
    confidence: float = 1.0
    source: str = "ocr"

    def to_dict(self):
        return {**asdict(self), "box": list(self.box)}


@dataclass
class Config:
    mode: str = "blur"
    sample_sec: float = 0.65
    min_hits: int = 2
    threshold: float = 0.65
    categories: tuple[str, ...] = ("subtitle", "text", "logo")
    padding: int = 5
    auto_logo: bool = True
    exclude: tuple[tuple[int, int, int, int], ...] = ()
    manual: tuple[Region, ...] = ()

    def validate(self):
        if self.mode not in ("blur", "inpaint"):
            raise VisualCleanupError("mode must be blur or inpaint")
        if not 0.15 <= self.sample_sec <= 10 or not 1 <= self.min_hits <= 15:
            raise VisualCleanupError("invalid sample_sec or min_hits")
        if not 0 <= self.threshold <= 1 or not 0 <= self.padding <= 64:
            raise VisualCleanupError("invalid threshold or padding")
        if not set(self.categories).issubset({"subtitle", "text", "logo"}):
            raise VisualCleanupError("invalid categories")


def _cv2():
    try:
        import cv2
        return cv2
    except ImportError as exc:
        raise VisualCleanupError("Install requirements-visual-cleanup.txt") from exc


def _clip(rect, width, height, pad=0):
    x1, y1, x2, y2 = map(int, rect)
    return (max(0, x1-pad), max(0, y1-pad),
            min(width, x2+pad), min(height, y2+pad))


def _overlap(a, b):
    x = max(0, min(a[2], b[2])-max(a[0], b[0]))
    y = max(0, min(a[3], b[3])-max(a[1], b[1]))
    return x*y


def _iou(a, b):
    shared = _overlap(a, b)
    area = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - shared
    return shared/area if area > 0 else 0


def _kind(rect, width, height):
    x1, y1, x2, y2 = rect
    cx = (x1+x2)/2/width
    cy = (y1+y2)/2/height
    ww = (x2-x1)/width
    hh = (y2-y1)/height
    # Narrow corner marks are more likely logos than bottom subtitles.
    if (cx < .18 or cx > .82) and (cy < .18 or cy > .83) and ww < .24 and hh < .14:
        return "logo"
    if cy > .70 and ww > .06 and hh < .16:
        return "subtitle"
    return "text"


class PaddleDetector:
    """PaddleOCR 3.x only; v2 ocr() output is not supported."""

    def __init__(self):
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise VisualCleanupError("Install PaddleOCR 3.x for OCR detection") from exc
        self.model = PaddleOCR(
            lang="ch", device="cpu", use_doc_orientation_classify=False,
            use_doc_unwarping=False, use_textline_orientation=False)

    def detect(self, frame):
        for result in self.model.predict(frame):
            for box, score in zip(result["rec_boxes"], result["rec_scores"]):
                yield tuple(map(int, box)), float(score)


def _safe_auto_logo_box(box, width, height):
    """Limit heuristic masks to small marks at the topmost image corners.

    A permanent picture-in-picture face is also temporally static and MUST NOT
    be auto-masked. This geometry is intentionally conservative.
    """
    x1, y1, x2, y2 = box
    return (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height
            and y1 <= .09*height and y2 <= .18*height
            and x2-x1 <= .23*width
            and (x2 <= .27*width or x1 >= .73*width))


def _static_logos(frames, duration, width, height):
    """Opaque unchanging top-corner overlay candidates; never infer transparent logos."""
    if len(frames) < 10:
        return []
    import numpy as np
    cv2 = _cv2()
    target_w = min(width, 320)
    target_h = max(1, round(height * target_w / width))
    stack = np.stack([
        cv2.cvtColor(cv2.resize(f, (target_w, target_h)),
                     cv2.COLOR_BGR2GRAY)
        for f in frames]).astype(np.float32)
    variation = stack.std(axis=0)
    if float(np.median(variation)) < 9:
        return []  # still scene: no meaningful watermark inference
    med = np.median(stack, axis=0).astype(np.uint8)
    edges = cv2.Canny(med, 75, 160) > 0
    mask = ((variation < 6) & edges).astype(np.uint8)*255
    boxes = []
    for xa, xb in ((0, .27), (.73, 1)):
        x1, x2 = round(target_w*xa), round(target_w*xb)
        y2 = round(target_h*.24)
        roi = cv2.dilate(mask[:y2, x1:x2], np.ones((3,3), np.uint8))
        count, _, stats, _ = cv2.connectedComponentsWithStats(roi)
        for i in range(1, count):
            x,y,w,h,area = stats[i]
            if area < 10 or w < 4 or h < 4 or w > .85*(x2-x1) or h > .8*y2:
                continue
            box = (round((x+x1)*width/target_w), round(y*height/target_h),
                   round((x+x1+w)*width/target_w), round((y+h)*height/target_h))
            # Static picture-in-picture faces look like logos to edge-variance
            # heuristics. Only auto-select the narrow uppermost corner strip;
            # everything lower requires explicit approval/manual boxes.
            if not _safe_auto_logo_box(box, width, height):
                continue
            boxes.append(Region(0, duration, box, "logo", .70, "static-heuristic"))
    return boxes


class VisualCleanup:
    def __init__(self, config=None, detector=None):
        self.config = config or Config()
        self.config.validate()
        self.detector = detector  # injection allows tests without model downloads

    def analyze(self, video, plan_path=None):
        cv2 = _cv2()
        path = Path(video)
        cap = cv2.VideoCapture(str(path))
        if not path.is_file() or not cap.isOpened():
            raise VisualCleanupError(f"Cannot open video: {path}")
        try:
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = float(cap.get(cv2.CAP_PROP_FPS))
            if width < 2 or height < 2 or not math.isfinite(fps) or fps <= 0:
                raise VisualCleanupError("Invalid video dimensions/fps")
            step = max(1, round(fps*self.config.sample_sec))
            detector = self.detector or PaddleDetector()
            tracks = []
            regions = []
            logo_frames = []
            sampled = 0
            frame_n = 0
            # Confirm a newly seen subtitle ~180ms later rather than waiting
            # for the next regular 650ms OCR sample. This catches short lines
            # without trusting one-frame false positives.
            quick_frames = max(1, round(fps * .18))
            last_sample_frame = -quick_frames
            subtitle_needs_check = False
            def finish_track(track, end_limit):
                box = tight_box(track.get("boxes", [track["box"]]), width, height)
                if track["kind"] == "subtitle":
                    start, end = refine_subtitle_bounds(
                        path, track["first_frame"], track["last_frame"],
                        track["first_box"], track["last_box"],
                        fps, end_limit, self.config.sample_sec)
                else:
                    margin = min(.15, step/fps/2)
                    start, end = max(0, track["first"]-margin), min(end_limit, track["last"]+margin)
                if end > start:
                    regions.append(Region(start, end, box, track["kind"],
                                          track["score"]/track["hits"]))
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                if (frame_n % step == 0 or
                        (subtitle_needs_check and frame_n - last_sample_frame >= quick_frames)):
                    t = frame_n/fps
                    if self.config.auto_logo and "logo" in self.config.categories:
                        # Keep thumbnails, never 32 full-resolution 4K frames.
                        thumb_w = min(320, width)
                        thumb_h = max(1, round(height * thumb_w / width))
                        thumb = cv2.resize(frame, (thumb_w, thumb_h))
                        if len(logo_frames) < 32:
                            logo_frames.append(thumb)
                        elif sampled % max(1, round(25/self.config.sample_sec)) == 0:
                            logo_frames[sampled % 32] = thumb
                    expired = [r for r in tracks if sampled - r["sample"] > 1]
                    tracks = [r for r in tracks if sampled - r["sample"] <= 1]
                    for r in expired:
                        if r["hits"] >= self.config.min_hits:
                            finish_track(r, t)
                    used = set()
                    for raw, score in detector.detect(frame):
                        if score < self.config.threshold:
                            continue
                        box = _clip(raw, width, height)
                        if box[2] <= box[0] or box[3] <= box[1]:
                            continue
                        if any(_overlap(box, e) >= .15*(box[2]-box[0])*(box[3]-box[1])
                               for e in self.config.exclude):
                            continue
                        kind = _kind(box, width, height)
                        if kind not in self.config.categories:
                            continue
                        best, best_score = None, .26
                        for i, r in enumerate(tracks):
                            if i in used or r["kind"] != kind or r["sample"] != sampled-1:
                                continue
                            match = _iou(r["box"], box)
                            if kind == "subtitle" and match < .27:
                                a = r["box"]
                                dy = abs((a[1]+a[3])/2-(box[1]+box[3])/2)
                                common = max(0, min(a[2],box[2])-max(a[0],box[0]))
                                if dy < max(10, (a[3]-a[1])*.65) and common > .45*min(a[2]-a[0],box[2]-box[0]):
                                    match = .27
                            if match > best_score:
                                best, best_score = i, match
                        if best is None:
                            tracks.append({"box":box, "kind":kind, "sample":sampled,
                                           "first":t, "last":t, "hits":1, "score":score,
                                           "boxes":[box], "first_box":box, "last_box":box,
                                           "first_frame":frame_n, "last_frame":frame_n})
                            used.add(len(tracks)-1)
                        else:
                            r = tracks[best]
                            a = r["box"]
                            r["box"] = (min(a[0],box[0]), min(a[1],box[1]),
                                        max(a[2],box[2]), max(a[3],box[3]))
                            r["boxes"].append(box)
                            r.update(last=t, sample=sampled, hits=r["hits"]+1,
                                     score=r["score"]+score, last_box=box,
                                     last_frame=frame_n)
                            used.add(best)
                    sampled += 1
                    last_sample_frame = frame_n
                    subtitle_needs_check = any(
                        r["kind"] == "subtitle" and r["hits"] == 1
                        and r["sample"] == sampled - 1 for r in tracks)
                frame_n += 1
            duration = frame_n/fps
            for r in tracks:
                if r["hits"] >= self.config.min_hits:
                    finish_track(r, duration)
            if self.config.auto_logo and "logo" in self.config.categories:
                for item in _static_logos(logo_frames, duration, width, height):
                    if any(_overlap(item.box, e) >= .15*(item.box[2]-item.box[0])*(item.box[3]-item.box[1])
                           for e in self.config.exclude):
                        continue
                    if not any(_iou(item.box, r.box) > .4 and r.kind == "logo" for r in regions):
                        regions.append(item)
            regions += [r for r in self.config.manual if r.kind in self.config.categories]
            plan = {"version":1, "source":str(path.resolve()), "width":width,
                    "height":height, "fps":fps, "frames":frame_n,
                    "sample_sec":step/fps,
                    "regions":[r.to_dict() for r in sorted(regions,key=lambda r:r.start)]}
            if plan_path is not None:
                target = Path(plan_path)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
            return plan
        finally:
            cap.release()

    def render(self, video, output, plan, *, ffmpeg="ffmpeg"):
        cv2 = _cv2()
        import numpy as np
        src, dst = Path(video), Path(output)
        if src.resolve() == dst.resolve() or not src.is_file():
            raise VisualCleanupError("Output must not overwrite input")
        if plan.get("version") != 1 or str(src.resolve()) != plan.get("source"):
            raise VisualCleanupError("Plan does not match input video")
        cap = cv2.VideoCapture(str(src))
        if not cap.isOpened():
            raise VisualCleanupError(f"Cannot open video: {src}")
        proc = None
        temp = None
        try:
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = float(cap.get(cv2.CAP_PROP_FPS))
            if w != plan["width"] or h != plan["height"] or fps <= 0:
                raise VisualCleanupError("Plan dimensions don't match video")
            from media.visual_temporal import TemporalCleanPlate, is_temporal_region
            reviewed_regions = [r for r in plan["regions"] if is_temporal_region(r)]
            clean_plate = (TemporalCleanPlate(
                src, reviewed_regions, fps, w, h,
                int(cap.get(cv2.CAP_PROP_FRAME_COUNT))) if reviewed_regions else None)
            dst.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix=".visual-clean-", suffix=".mp4", dir=dst.parent)
            os.close(fd)
            temp = Path(name)
            cmd = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
                   "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s",
                   f"{w}x{h}", "-r", f"{fps:.8f}", "-i", "pipe:0", "-an",
                   "-c:v", "libx264", "-crf", "18", "-preset", "fast",
                   "-pix_fmt", "yuv420p", str(temp)]
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
            upcoming = sorted(plan["regions"], key=lambda r:r["start"])
            current, cursor, frame_n = [], 0, 0
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                t = frame_n/fps
                while cursor < len(upcoming) and upcoming[cursor]["start"] <= t:
                    current.append(upcoming[cursor])
                    cursor += 1
                current = [r for r in current if r["end"] > t]
                if clean_plate is not None:
                    frame = clean_plate.apply(frame, frame_n)
                # A manually reviewed clean-plate covering an OCR text box
                # supersedes auto-blur; never erase freshly reconstructed
                # background by applying the old OCR mask a second time.
                approved = [r for r in current
                            if r.get("source") in ("temporal-clean-plate", "flat-strip-repaint")]
                standard = []
                for r in current:
                    if is_temporal_region(r):
                        continue
                    area = max(1, (r["box"][2]-r["box"][0]) *
                                  (r["box"][3]-r["box"][1]))
                    if any(_overlap(r["box"], q["box"]) > .5*area for q in approved):
                        continue
                    standard.append(r)
                if standard and self.config.mode == "inpaint":
                    mask = np.zeros((h, w), dtype=np.uint8)
                    for r in standard:
                        rect, selected = pixel_mask(frame, r["box"], r["kind"],
                                                    padding=min(self.config.padding, 2))
                        x1, y1, x2, y2 = rect
                        if selected.size:
                            mask[y1:y2, x1:x2] = cv2.bitwise_or(
                                mask[y1:y2, x1:x2], selected)
                    if mask.any():
                        frame = cv2.inpaint(frame, mask, 3, cv2.INPAINT_TELEA)
                elif standard:
                    # ROI-only blur: do not allocate multiple whole-frame float32
                    # arrays when a tiny subtitle/logo occupies 1% of a 4K frame.
                    for r in standard:
                        rect, selected = pixel_mask(frame, r["box"], r["kind"],
                                                    padding=min(self.config.padding, 2))
                        x1, y1, x2, y2 = rect
                        if not selected.size or not selected.any():
                            continue
                        border = 36  # 3 sigma of Gaussian blur radius 12
                        bx1, by1 = max(0,x1-border), max(0,y1-border)
                        bx2, by2 = min(w,x2+border), min(h,y2+border)
                        surrounding = frame[by1:by2,bx1:bx2]
                        blurred = cv2.GaussianBlur(surrounding,(0,0),12)
                        patch = frame[y1:y2,x1:x2].astype(np.float32)
                        blurred_patch = blurred[y1-by1:y2-by1,
                                                x1-bx1:x2-bx1].astype(np.float32)
                        alpha = cv2.GaussianBlur(selected,(0,0),1).astype(np.float32)/255
                        frame[y1:y2,x1:x2] = np.clip(
                            patch*(1-alpha[:,:,None]) +
                            blurred_patch*alpha[:,:,None],0,255).astype(np.uint8)
                try:
                    proc.stdin.write(frame.tobytes())
                except BrokenPipeError as exc:
                    raise VisualCleanupError("FFmpeg stopped during cleanup") from exc
                frame_n += 1
            proc.stdin.close()
            err = proc.stderr.read()
            if proc.wait() != 0 or temp.stat().st_size == 0:
                raise VisualCleanupError("FFmpeg cleanup: "+err.decode(errors="replace")[-500:])
            os.replace(temp,dst)
            return dst
        finally:
            cap.release()
            if proc is not None and proc.poll() is None:
                proc.kill()
                proc.wait()
            if temp is not None:
                temp.unlink(missing_ok=True)

    def process(self, video, output, *, plan_path=None, ffmpeg="ffmpeg"):
        plan = self.analyze(video, plan_path)
        return self.render(video, output, plan, ffmpeg=ffmpeg)
