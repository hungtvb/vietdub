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

import logging
import os
import subprocess
import tempfile
from pathlib import Path

from media import _bin
from media.output import next_available_output_path, publish_no_replace

log = logging.getLogger("vietdub.render")


class RenderError(Exception):
    pass


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
    for f, name in ((video_in, "video"), (mixed_wav, "audio đã trộn")):
        if not f.exists():
            raise RenderError(f"Không tìm thấy {name}: {f}")

    if sub_mode == "srt":
        cmd = [_bin.ffmpeg_cmd(), "-y", "-i", str(video_in), "-i", str(mixed_wav),
               "-map", "0:v", "-map", "1:a",
               "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
               "-shortest"]
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
               "-shortest"]
    else:
        raise RenderError(f"sub_mode không hợp lệ: {sub_mode} (chọn 'burn' hoặc 'srt')")

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
