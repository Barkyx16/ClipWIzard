"""Render a clip from a source video with a social-media friendly layout."""

from __future__ import annotations

import shutil
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

from ..analysis.smartcrop import crop_x_expression
from .ffmpeg import ProgressFn, run_with_progress

ASPECTS = {
    # name: (width, height)
    "landscape": (1920, 1080),
    "vertical_blur": (1080, 1920),
    "vertical_crop": (1080, 1920),
    "vertical_smart": (1080, 1920),
    "square": (1080, 1080),
}

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]


@dataclass
class RenderOptions:
    aspect: str = "vertical_blur"
    crop_x: float = 0.5  # 0 = left edge, 1 = right edge (vertical_crop only)
    title: str | None = None  # burned-in title text; None/"" = no overlay
    quality: str = "high"  # "high" or "fast"
    # vertical_smart: (seconds since clip start, crop centre 0..1) keyframes
    crop_keys: list[tuple[float, float]] = field(default_factory=list)


def _escape_filter_path(p: Path | str) -> str:
    # Escape characters that are special inside an ffmpeg filter argument.
    return str(p).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


def find_font(preferred: str | None) -> str | None:
    if preferred and Path(preferred).exists():
        return preferred
    for cand in FONT_CANDIDATES:
        if Path(cand).exists():
            return cand
    return None


def _even(x: float) -> int:
    return max(2, int(x) // 2 * 2)


def strip_unrenderable(text: str) -> str:
    """Drop emoji / pictographs: the bundled fonts have no glyphs for them."""
    out = []
    for ch in text:
        cp = ord(ch)
        if cp > 0xFFFF or 0x2600 <= cp <= 0x27BF or cp in (0xFE0F, 0x200D, 0x20E3):
            continue
        out.append(ch)
    return " ".join("".join(out).split())


def _title_filters(title: str, out_w: int, out_h: int, work: Path, font: str | None,
                   layout: str) -> list[str]:
    width_chars = 22 if out_w < out_h else 34
    lines = textwrap.wrap(strip_unrenderable(title), width=width_chars)[:3]
    if not lines:
        return []
    size = int(out_w * (0.062 if out_w < out_h else 0.038))
    line_h = int(size * 1.3)
    if layout == "vertical_blur":
        # Sit in the blurred band above the gameplay.
        fg_h = out_w * 9 / 16
        band_bottom = (out_h - fg_h) / 2
        top = int(band_bottom - line_h * len(lines) - out_h * 0.03)
    else:
        top = int(out_h * 0.07)
    filters = []
    for i, line in enumerate(lines):
        tf = work / f"title_{i}.txt"
        tf.write_text(line, encoding="utf-8")
        parts = [
            f"textfile='{_escape_filter_path(tf)}'",
            f"fontsize={size}",
            "fontcolor=white",
            "borderw=4",
            "bordercolor=black@0.85",
            "shadowx=0",
            "shadowy=3",
            "shadowcolor=black@0.6",
            "x=(w-text_w)/2",
            f"y={top + i * line_h}",
        ]
        if font:
            parts.insert(1, f"fontfile='{_escape_filter_path(font)}'")
        filters.append("drawtext=" + ":".join(parts))
    return filters


def build_command(src: Path, out: Path, start: float, end: float, src_w: int, src_h: int,
                  has_audio: bool, opts: RenderOptions, work: Path,
                  font: str | None) -> list[str]:
    duration = max(0.5, end - start)
    out_w, out_h = ASPECTS.get(opts.aspect, ASPECTS["vertical_blur"])

    if opts.aspect == "landscape":
        # Keep the source aspect ratio, cap at 1080p.
        scale_h = min(src_h, 1080)
        out_h = _even(scale_h)
        out_w = _even(src_w * out_h / max(1, src_h))
        graph = f"[0:v]scale={out_w}:{out_h}:flags=lanczos,setsar=1[base]"
    elif opts.aspect in ("vertical_crop", "vertical_smart"):
        target = out_w / out_h
        if src_w / src_h > target:
            cw, ch = _even(src_h * target), _even(src_h)
            if opts.aspect == "vertical_smart" and opts.crop_keys:
                cx: int | str = "'" + crop_x_expression(opts.crop_keys, src_w, cw) + "'"
            else:
                centre = 0.5 if opts.aspect == "vertical_smart" else opts.crop_x
                cx = int((src_w - cw) * min(1.0, max(0.0, centre)))
            cy = 0
        else:
            cw, ch = _even(src_w), _even(src_w / target)
            cx, cy = 0, int((src_h - ch) / 2)
        graph = f"[0:v]crop={cw}:{ch}:{cx}:{cy},scale={out_w}:{out_h}:flags=lanczos,setsar=1[base]"
    else:
        # Blurred fill: the full frame centred over a blurred, zoomed copy.
        bw, bh = out_w // 4, out_h // 4
        graph = (
            "[0:v]split=2[bgsrc][fgsrc];"
            f"[bgsrc]scale={bw}:{bh}:force_original_aspect_ratio=increase,crop={bw}:{bh},"
            f"boxblur=12:2,eq=brightness=-0.06:saturation=1.2,scale={out_w}:{out_h}[bg];"
            f"[fgsrc]scale={out_w}:{out_h}:force_original_aspect_ratio=decrease:flags=lanczos[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[base]"
        )

    titles = _title_filters(opts.title, out_w, out_h, work, font, opts.aspect) if opts.title else []
    if titles:
        graph += ";[base]" + ",".join(titles) + "[vout]"
    else:
        graph += ";[base]null[vout]"

    preset, crf = ("veryfast", "20") if opts.quality == "high" else ("ultrafast", "26")
    cmd = [
        "ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y",
        "-ss", f"{start:.3f}", "-i", str(src), "-t", f"{duration:.3f}",
        "-filter_complex", graph, "-map", "[vout]",
    ]
    if has_audio:
        fade_out = max(0.0, duration - 0.35)
        cmd += [
            "-map", "0:a:0?",
            "-af", f"afade=t=in:st=0:d=0.15,afade=t=out:st={fade_out:.3f}:d=0.35",
            "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
        ]
    else:
        cmd += ["-an"]
    cmd += [
        "-c:v", "libx264", "-preset", preset, "-crf", crf, "-pix_fmt", "yuv420p",
        "-r", "60", "-fps_mode", "cfr",
        "-movflags", "+faststart",
        "-progress", "pipe:1", "-nostats",
        str(out),
    ]
    return cmd


def render_clip(src: Path, out: Path, start: float, end: float, src_w: int, src_h: int,
                src_fps: float, has_audio: bool, opts: RenderOptions, work: Path,
                font_pref: str | None = None, progress: ProgressFn | None = None) -> Path:
    work.mkdir(parents=True, exist_ok=True)
    font = find_font(font_pref)
    cmd = build_command(src, out, start, end, src_w, src_h, has_audio, opts, work, font)
    # Don't upsample low-fps sources to 60.
    fps = 60 if src_fps > 45 else 30
    cmd[cmd.index("-r") + 1] = str(fps)
    tmp = out.with_suffix(".part.mp4")
    cmd[-1] = str(tmp)
    run_with_progress(cmd, end - start, progress, work / "render.log")
    shutil.move(str(tmp), str(out))
    return out
