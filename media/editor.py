# VietDub - Vietnamese dubbing for Chinese videos (PySide6 desktop app)
# Copyright (C) 2026 VietDub contributors
# License: GNU General Public License v3.0 (see LICENSE)
"""Export a trimmed dub with edited subtitles and an optional logo."""
from __future__ import annotations

import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Sequence

from media import _bin
from media.extract import probe
from media.render import RenderError, _ass_color, _escape_sub_path
from media.subs import write_srt
from project.schema import Segment


def export_edit(video_in: str | Path, mixed_wav: str | Path,
                segments: Sequence[Segment], out_mp4: str | Path,
                trim_start: float, trim_end: float, *,
                logo_path: str = "", logo_corner: str = "top-right",
                logo_width_pct: int = 12, logo_opacity_pct: int = 85,
                sub_mode: str = "burn", crf: int = 20, font: str = "",
                font_size: int = 0, font_color: str = "") -> Path:
    source, audio, target = Path(video_in), Path(mixed_wav), Path(out_mp4)
    if not source.is_file() or not audio.is_file():
        raise RenderError("Không tìm thấy video gốc hoặc audio đã trộn.")
    if target.resolve() in {source.resolve(), audio.resolve()}:
        raise RenderError("Đường dẫn xuất không được ghi đè video hoặc audio gốc.")
    if trim_start < 0 or trim_end <= trim_start:
        raise RenderError("Khoảng cắt video không hợp lệ.")
    if sub_mode not in {"burn", "srt"}:
        raise RenderError("Chế độ phụ đề không hợp lệ.")
    if logo_path and not Path(logo_path).is_file():
        raise RenderError(f"Không tìm thấy logo: {logo_path}")
    if logo_corner not in {"top-left", "top-right", "bottom-left", "bottom-right"}:
        raise RenderError("Vị trí logo không hợp lệ.")
    if not 5 <= logo_width_pct <= 50 or not 0 <= logo_opacity_pct <= 100:
        raise RenderError("Kích thước hoặc độ mờ logo không hợp lệ.")

    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.stem + ".partial.mp4")
    temp_srt = temp.with_suffix(".srt")
    target_srt = target.with_suffix(".srt")
    # Preserve the editor's absolute timeline; the exported file begins at 0.
    clipped = [replace(s, start=max(s.start, trim_start) - trim_start,
                       end=min(s.end, trim_end) - trim_start)
               for s in segments if s.text_vi.strip()
               and s.end > trim_start and s.start < trim_end]
    srt = write_srt(clipped, temp_srt)
    try:
        filters = [
            f"[0:v]trim=start={trim_start:.3f}:end={trim_end:.3f},"
            "setpts=PTS-STARTPTS[v0]",
            f"[1:a]atrim=start={trim_start:.3f}:end={trim_end:.3f},"
            "asetpts=PTS-STARTPTS[a]",
        ]
        cmd = [_bin.ffmpeg_cmd(), "-y", "-v", "error", "-i", str(source),
               "-i", str(audio)]
        video_label = "v0"
        if logo_path:
            stream = next((s for s in probe(source).get("streams", [])
                           if s.get("codec_type") == "video"), None)
            width = int((stream or {}).get("width") or 0)
            height = int((stream or {}).get("height") or 0)
            if width <= 0 or height <= 0:
                raise RenderError("Không đọc được kích thước video để đặt logo.")
            logo_width = max(8, round(width * logo_width_pct / 100))
            margin = max(8, round(min(width, height) * 0.025))
            x = str(margin) if logo_corner.endswith("left") else f"W-w-{margin}"
            y = str(margin) if logo_corner.startswith("top") else f"H-h-{margin}"
            cmd += ["-loop", "1", "-i", str(logo_path)]
            filters.append(
                f"[2:v]format=rgba,scale={logo_width}:-1,"
                f"colorchannelmixer=aa={logo_opacity_pct / 100:.3f}[logo]")
            filters.append(f"[v0][logo]overlay=x={x}:y={y}:shortest=1[v1]")
            video_label = "v1"
        if sub_mode == "burn" and clipped:
            sub_filter = f"subtitles={_escape_sub_path(srt)}"
            styles = []
            if font:
                sub_filter += f":fontsdir='{Path(font).parent}'"
                styles.append(f"FontName={Path(font).stem}")
            if font_size > 0:
                styles.append(f"FontSize={font_size}")
            if font_color.strip():
                styles.append(f"PrimaryColour={_ass_color(font_color)}")
            if styles:
                sub_filter += f":force_style='{','.join(styles)}'"
            filters.append(f"[{video_label}]{sub_filter}[vout]")
            video_label = "vout"
        cmd += ["-filter_complex", ";".join(filters),
                "-map", f"[{video_label}]", "-map", "[a]",
                "-c:v", "libx264", "-crf", str(crf), "-preset", "medium",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                "-t", f"{trim_end - trim_start:.3f}", str(temp)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0 or not temp.is_file():
            raise RenderError(f"Xuất video thất bại:\n{result.stderr[-900:]}")
        temp.replace(target)
        temp_srt.replace(target_srt)
        return target
    finally:
        temp.unlink(missing_ok=True)
        temp_srt.unlink(missing_ok=True)
