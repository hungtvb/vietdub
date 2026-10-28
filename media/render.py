# VietDub - Vietnamese dubbing for Chinese videos (PySide6 desktop app)
# Copyright (C) 2026 VietDub contributors
# License: GNU General Public License v3.0 (see LICENSE)
"""Step [8] - render: mux mixed audio + subtitles into the final video.

- sub_mode="burn": hard-burn via the subtitles filter. The .srt is passed
  as a FILE (escaped path) - text is never inlined into filter args
  (edge case 11).
- sub_mode="srt": stream-copy video, mux audio, write a sidecar .srt.

Video stream is copied untouched when not burning (fast, lossless).
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from media import _bin
from media.output import next_available_output_path, publish_no_replace

log = logging.getLogger("vietdub.render")


class RenderError(Exception):
    pass


def _video_duration_seconds(video: Path) -> float:
    """Get the actual video-stream duration for accurate audio padding.

    Do NOT use -af apad together with -shortest on static FFmpeg 7: the
    infinite audio stream can cause the mux to hang even after video EOF.
    Prefer video-stream metadata, with a decoded CFR fallback when the
    portable FFmpeg distribution has no ffprobe executable.
    """
    probe_bin = _bin.ffprobe_cmd()
    if shutil.which(probe_bin) or Path(probe_bin).is_file():
        p = subprocess.run(
            [probe_bin, "-v", "error", "-show_streams", "-show_format",
             "-of", "json", str(video)], capture_output=True, text=True)
        if p.returncode == 0:
            try:
                info = json.loads(p.stdout)
                stream = next((x for x in info.get("streams", [])
                               if x.get("codec_type") == "video"), {})
                frames = int(stream.get("nb_frames") or 0)
                rate = stream.get("avg_frame_rate") or stream.get("r_frame_rate") or ""
                if frames > 0 and "/" in rate:
                    num, den = map(int, rate.split("/"))
                    if num > 0 and den > 0:
                        return frames * den / num
                duration = float(stream.get("duration") or
                                 info.get("format", {}).get("duration") or 0)
                if math.isfinite(duration) and duration > 0:
                    return duration
            except (ValueError, TypeError, StopIteration):
                pass
    try:
        import cv2
        cap = cv2.VideoCapture(str(video))
        try:
            n = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            fps = cap.get(cv2.CAP_PROP_FPS)
            if cap.isOpened() and math.isfinite(fps) and fps > 0 and n > 0:
                return n / fps
        finally:
            cap.release()
    except ImportError:
        pass
    # Portable FFmpeg build without ffprobe or optional OpenCV.
    p = subprocess.run([_bin.ffmpeg_cmd(), "-hide_banner", "-i", str(video)],
                       capture_output=True, text=True)
    match = re.search(r"Duration: (\d{2}):(\d{2}):(\d{2}\.\d+)", p.stderr)
    if match:
        hh, mm, ss = match.groups()
        duration = int(hh)*3600 + int(mm)*60 + float(ss)
        if duration > 0:
            return duration
    raise RenderError(f"Cannot determine source VIDEO duration for {video}")


def _escape_sub_path(srt_path: Path) -> str:
    # subtitles filter escaping: single-quote and colon must be escaped.
    # Convert Windows backslashes to forward slashes FIRST, so the escape
    # backslashes we add afterwards are never touched.
    p = str(srt_path).replace("\\", "/")
    return p.replace(":", "\\:").replace("'", "\\'")


def _ass_color(hex_rrggbb: str) -> str:
    """Hex 'RRGGBB' (như user nhập) -> màu libass '&H00BBGGRR'."""
    h = (hex_rrggbb or "").strip().lstrip("#")
    if len(h) == 3:  # dạng rút gọn "FFF" -> "FFFFFF"
        h = "".join(c * 2 for c in h)
    if len(h) != 6 or any(c not in "0123456789abcdefABCDEF" for c in h):
        raise RenderError(f"Màu phụ đề không hợp lệ: '{hex_rrggbb}' "
                          "(nhập hex 6 ký tự, vd FFFF00 cho vàng).")
    rr, gg, bb = h[0:2], h[2:4], h[4:6]
    return f"&H00{bb}{gg}{rr}"


def _temporary_output(parent: Path, suffix: str) -> Path:
    """Reserve a unique output name in the final destination directory."""
    fd, name = tempfile.mkstemp(prefix=".vietdub-", suffix=suffix, dir=parent)
    os.close(fd)
    return Path(name)


def _cleanup_temporary(*paths: Path | None) -> None:
    for path in paths:
        if path is not None:
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                log.warning("Could not remove temporary output %s: %s", path, exc)


def _remove_our_published_link(source: Path, target: Path) -> None:
    """Remove a destination only while it still aliases our temp artifact."""
    try:
        same_file = os.path.samefile(source, target)
    except FileNotFoundError:
        return
    if same_file:
        target.unlink(missing_ok=True)


def _publish_rendered_mp4(temp_mp4: Path, requested: Path, selected: Path,
                          temp_srt: Path | None = None) -> Path:
    """Publish an export, retrying when either member of an SRT pair collides.

    Keep both temporary files until the pair is complete so a sidecar race can
    roll back the MP4 link and try the next common basename.
    """
    paired = (".srt",) if temp_srt is not None else ()
    while True:
        # A paired name may have appeared while ffmpeg was rendering. Pick a
        # fresh pair before publishing the first completed member.
        if os.path.lexists(selected) or any(
                os.path.lexists(selected.with_suffix(ext)) for ext in paired):
            selected = next_available_output_path(requested, paired)
        if temp_srt is None:
            try:
                publish_no_replace(temp_mp4, selected)
            except FileExistsError:
                selected = next_available_output_path(requested, paired)
                continue
            return selected

        try:
            os.link(temp_mp4, selected)
        except FileExistsError:
            selected = next_available_output_path(requested, paired)
            continue

        sidecar = selected.with_suffix(".srt")
        try:
            os.link(temp_srt, sidecar)
        except FileExistsError:
            # Remove the MP4 only while it still refers to our temporary file;
            # this avoids deleting a path another process replaced meanwhile.
            try:
                _remove_our_published_link(temp_mp4, selected)
            except OSError as exc:
                raise RenderError(
                    f"Không thể hoàn tất cặp video/phụ đề; kiểm tra {selected}"
                ) from exc
            selected = next_available_output_path(requested, paired)
            continue
        except OSError as exc:
            try:
                _remove_our_published_link(temp_mp4, selected)
            except OSError as cleanup_exc:
                raise RenderError(
                    f"Không thể xuất phụ đề; video có thể còn tại {selected}"
                ) from cleanup_exc
            raise RenderError(
                f"Không thể xuất phụ đề cạnh video: {selected}"
            ) from exc
        return selected


def render(video_in: str | Path, mixed_wav: str | Path, srt_path: str | Path,
           out_mp4: str | Path, sub_mode: str = "burn",
           crf: int = 20, font: str = "",
           font_size: int = 0, font_color: str = "") -> Path:
    video_in, mixed_wav, out_mp4 = Path(video_in), Path(mixed_wav), Path(out_mp4)
    srt_path = Path(srt_path)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    video_duration = _video_duration_seconds(video_in)
    for f, name in ((video_in, "video"), (mixed_wav, "audio đã trộn")):
        if not f.exists():
            raise RenderError(f"Không tìm thấy {name}: {f}")

    if sub_mode in {"srt", "none"}:
        cmd = [_bin.ffmpeg_cmd(), "-y", "-i", str(video_in), "-i", str(mixed_wav),
               "-map", "0:v", "-map", "1:a",
               "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
               "-af", "apad", "-t", f"{video_duration:.8f}"]
    elif sub_mode == "burn":
        if not srt_path.exists():
            raise RenderError(f"Không tìm thấy file phụ đề: {srt_path}")
        sub_filter = f"subtitles={_escape_sub_path(srt_path)}"
        force_parts = []
        if font:
            sub_filter += f":fontsdir='{Path(font).parent}'"
            force_parts.append(f"FontName={Path(font).stem}")
        if font_size and int(font_size) > 0:
            force_parts.append(f"FontSize={int(font_size)}")
        if font_color and str(font_color).strip():
            force_parts.append(f"PrimaryColour={_ass_color(font_color)}")
        if force_parts:
            sub_filter += f":force_style='{','.join(force_parts)}'"
        # edge 8-render fallback: burn needs re-encode; if font missing,
        # ffmpeg falls back to its default font - we only warn.
        cmd = [_bin.ffmpeg_cmd(), "-y", "-i", str(video_in), "-i", str(mixed_wav),
               "-filter_complex", f"[0:v]{sub_filter}[v]",
               "-map", "[v]", "-map", "1:a",
               "-c:v", "libx264", "-crf", str(crf), "-preset", "medium",
               "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "192k",
               "-af", "apad", "-t", f"{video_duration:.8f}"]
    else:
        raise RenderError(f"sub_mode không hợp lệ: {sub_mode} (chọn 'burn', 'srt' hoặc 'none')")

    paired = (".srt",) if sub_mode == "srt" else ()
    selected = next_available_output_path(out_mp4, paired)
    temp_mp4 = _temporary_output(out_mp4.parent, ".mp4")
    temp_srt = None
    try:
        if sub_mode == "srt":
            temp_srt = _temporary_output(out_mp4.parent, ".srt")
            temp_srt.write_bytes(srt_path.read_bytes())
        cmd.append(str(temp_mp4))
        log.debug("render cmd: %s", " ".join(cmd[:6]) + " ...")
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode != 0 or not temp_mp4.is_file():
            raise RenderError(f"Ghép video thất bại:\n{p.stderr[-600:]}")
        selected = _publish_rendered_mp4(temp_mp4, out_mp4, selected, temp_srt)
        log.info("rendered -> %s (sub_mode=%s)", selected, sub_mode)
        return selected
    finally:
        _cleanup_temporary(temp_mp4, temp_srt)
