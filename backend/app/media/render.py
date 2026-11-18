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
    "vertical_facecam": (1080, 1920),
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
    # vertical_facecam: facecam rectangle in source, normalised {x, y, w, h}
    facecam: dict[str, float] | None = None
    # Burned-in captions (an ASS subtitle file written by media.captions)
    captions_ass: Path | None = None
    # Channel handle shown in a corner, e.g. "@clipking"
    watermark: str | None = None


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
                   layout: str, seam: int | None = None) -> list[str]:
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
    elif layout == "facecam" and seam is not None:
        # Straddle the seam between the facecam and the gameplay.
        top = int(seam - line_h * len(lines) / 2)
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


def _facecam_graph(src_w: int, src_h: int, out_w: int, out_h: int,
                   opts: RenderOptions) -> tuple[str, int]:
    """Facecam stacked on top of a full-width gameplay crop."""
    fc = opts.facecam or {}
    fx = int(min(max(fc.get("x", 0.0), 0.0), 0.95) * src_w)
    fy = int(min(max(fc.get("y", 0.0), 0.0), 0.95) * src_h)
    fw = _even(max(16, min(fc.get("w", 0.25) * src_w, src_w - fx)))
    fh = _even(max(16, min(fc.get("h", 0.25) * src_h, src_h - fy)))
    # Top panel keeps roughly the facecam's shape, within sensible bounds.
    top_h = _even(min(max(out_w * fh / fw, out_h * 0.25), out_h * 0.45))
    bot_h = out_h - top_h
    target = out_w / bot_h
    if src_w / src_h > target:
        gw, gh = _even(src_h * target), _even(src_h)
        if opts.crop_keys:
            gx: int | str = "'" + crop_x_expression(opts.crop_keys, src_w, gw) + "'"
        else:
            gx = int((src_w - gw) / 2)
        gy = 0
    else:
        gw, gh = _even(src_w), _even(src_w / target)
        gx, gy = 0, int((src_h - gh) / 2)
    graph = (
        "[0:v]split=2[camsrc][gamesrc];"
        f"[camsrc]crop={fw}:{fh}:{fx}:{fy},scale={out_w}:{top_h}:force_original_aspect_ratio=increase:"
        f"flags=lanczos,crop={out_w}:{top_h}[cam];"
        f"[gamesrc]crop={gw}:{gh}:{gx}:{gy},scale={out_w}:{bot_h}:flags=lanczos[game];"
        f"[cam][game]vstack=inputs=2,drawbox=x=0:y={top_h - 3}:w={out_w}:h=6:color=black@0.9:t=fill,"
        "setsar=1[base]"
    )
    return graph, top_h


def output_size(aspect: str, src_w: int, src_h: int) -> tuple[int, int]:
    if aspect == "landscape":
        out_h = _even(min(src_h, 1080))
        return _even(src_w * out_h / max(1, src_h)), out_h
    return ASPECTS.get(aspect, ASPECTS["vertical_blur"])


def _watermark_filter(text: str, out_w: int, out_h: int, work: Path, font: str | None) -> str:
    tf = work / "watermark.txt"
    tf.write_text(strip_unrenderable(text)[:40], encoding="utf-8")
    size = int(min(out_w, out_h) * 0.038)
    parts = [
        f"textfile='{_escape_filter_path(tf)}'",
        f"fontsize={size}",
        "fontcolor=white@0.85",
        "borderw=2",
        "bordercolor=black@0.6",
        f"x=w-text_w-{int(out_w * 0.04)}",
        f"y=h-text_h-{int(out_h * (0.12 if out_h > out_w else 0.05))}",
    ]
    if font:
        parts.insert(1, f"fontfile='{_escape_filter_path(font)}'")
    return "drawtext=" + ":".join(parts)


def build_command(src: Path, out: Path, start: float, end: float, src_w: int, src_h: int,
                  has_audio: bool, opts: RenderOptions, work: Path,
                  font: str | None) -> list[str]:
    duration = max(0.5, end - start)
    out_w, out_h = ASPECTS.get(opts.aspect, ASPECTS["vertical_blur"])
    seam = 0

    if opts.aspect == "landscape":
        # Keep the source aspect ratio, cap at 1080p.
        scale_h = min(src_h, 1080)
        out_h = _even(scale_h)
        out_w = _even(src_w * out_h / max(1, src_h))
        graph = f"[0:v]scale={out_w}:{out_h}:flags=lanczos,setsar=1[base]"
    elif opts.aspect == "vertical_facecam" and opts.facecam:
        graph, seam = _facecam_graph(src_w, src_h, out_w, out_h, opts)
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

    layout = "facecam" if opts.aspect == "vertical_facecam" and opts.facecam else opts.aspect
    titles = _title_filters(opts.title, out_w, out_h, work, font, layout,
                            seam=seam if layout == "facecam" else None) if opts.title else []
    overlays = list(titles)
    if opts.watermark:
        overlays.append(_watermark_filter(opts.watermark, out_w, out_h, work, font))
    if opts.captions_ass is not None:
        overlays.append(f"subtitles=filename='{_escape_filter_path(opts.captions_ass)}'")
    if overlays:
        graph += ";[base]" + ",".join(overlays) + "[vout]"
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


TRANSITIONS = {"fade", "fadeblack", "slideleft", "cut"}


def join_segments(parts: list[Path], out: Path, transition: str, has_audio: bool, work: Path,
                  progress: ProgressFn | None = None, fade: float = 0.4) -> Path:
    """Concatenate rendered segments (same size/fps/codec) into one video."""
    from .ffmpeg import probe

    if not parts:
        raise ValueError("Nothing to join")
    work.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".part.mp4")
    if len(parts) == 1:
        shutil.copy(parts[0], tmp)
        shutil.move(str(tmp), str(out))
        return out

    durations = [probe(p).duration for p in parts]
    if transition not in TRANSITIONS:
        transition = "fade"
    fade = min(fade, min(durations) / 3)

    if transition == "cut" or fade < 0.05:
        listing = work / "concat.txt"
        listing.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in parts), encoding="utf-8")
        cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", "-f", "concat", "-safe", "0",
               "-i", str(listing), "-c", "copy", "-movflags", "+faststart",
               "-progress", "pipe:1", "-nostats", str(tmp)]
        run_with_progress(cmd, sum(durations), progress, work / "join.log")
        shutil.move(str(tmp), str(out))
        return out

    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y"]
    for p in parts:
        cmd += ["-i", str(p)]
    chains = [f"[{i}:v]settb=AVTB,setpts=PTS-STARTPTS,format=yuv420p[v{i}]" for i in range(len(parts))]
    prev, offset = "v0", 0.0
    for i in range(1, len(parts)):
        offset += durations[i - 1] - fade
        label = f"x{i}"
        chains.append(f"[{prev}][v{i}]xfade=transition={transition}:duration={fade:.3f}:"
                      f"offset={offset:.3f}[{label}]")
        prev = label
    maps = ["-map", f"[{prev}]"]
    if has_audio:
        aprev = "0:a"
        for i in range(1, len(parts)):
            label = f"a{i}"
            chains.append(f"[{aprev}][{i}:a]acrossfade=d={fade:.3f}:c1=tri:c2=tri[{label}]")
            aprev = label
        maps += ["-map", f"[{aprev}]", "-c:a", "aac", "-b:a", "160k", "-ar", "48000"]
    total = sum(durations) - fade * (len(parts) - 1)
    cmd += ["-filter_complex", ";".join(chains), *maps,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", str(tmp)]
    run_with_progress(cmd, total, progress, work / "join.log")
    shutil.move(str(tmp), str(out))
    return out
