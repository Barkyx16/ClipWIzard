"""Thin wrappers around the ffmpeg / ffprobe command line tools."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

ProgressFn = Callable[[float], None]


class FFmpegError(RuntimeError):
    pass


@dataclass
class ProbeResult:
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool


def ensure_available() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            raise FFmpegError(f"{tool} is not installed or not on PATH")


def _parse_rate(rate: str | None) -> float:
    if not rate or rate == "0/0":
        return 0.0
    if "/" in rate:
        num, den = rate.split("/", 1)
        try:
            return float(num) / float(den) if float(den) else 0.0
        except ValueError:
            return 0.0
    try:
        return float(rate)
    except ValueError:
        return 0.0


def probe(path: Path) -> ProbeResult:
    cmd = [
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise FFmpegError(f"ffprobe could not read this file: {proc.stderr.strip()[:300]}")
    info = json.loads(proc.stdout or "{}")
    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"
                  and not s.get("disposition", {}).get("attached_pic")), None)
    if video is None:
        raise FFmpegError("No video stream found in this file")
    has_audio = any(s.get("codec_type") == "audio" for s in streams)

    duration = 0.0
    for candidate in (info.get("format", {}).get("duration"), video.get("duration")):
        try:
            duration = float(candidate)
            if duration > 0:
                break
        except (TypeError, ValueError):
            continue
    if duration <= 0:
        raise FFmpegError("Could not determine the video duration")

    width, height = int(video.get("width", 0)), int(video.get("height", 0))
    # Respect rotation metadata (phone recordings).
    rotation = 0
    for side in video.get("side_data_list", []) or []:
        if "rotation" in side:
            rotation = int(side["rotation"])
    if abs(rotation) in (90, 270):
        width, height = height, width

    fps = _parse_rate(video.get("avg_frame_rate")) or _parse_rate(video.get("r_frame_rate")) or 30.0
    return ProbeResult(duration=duration, width=width, height=height, fps=fps, has_audio=has_audio)


# ------------------------------------------------------------------ decoding

ANALYSIS_FPS = 4  # frames per second sampled for motion analysis (== 1 / HOP)
ANALYSIS_W, ANALYSIS_H = 64, 36
AUDIO_SR = 8000


def decode_for_analysis(
    path: Path,
    audio_out: Path,
    has_audio: bool,
    duration: float,
    on_frames: Callable[[bytes], None],
    progress: ProgressFn | None = None,
) -> None:
    """Decode the video once, writing low-rate mono PCM to ``audio_out`` and
    streaming tiny grayscale frames to ``on_frames``.

    Doing both in a single ffmpeg process means the (expensive) video decode
    only happens once, which matters for multi-hour gameplay recordings.
    """
    # Only ~4 frames/s are sampled, so skip decoding non-reference (B) frames:
    # ~25% faster on typical OBS/stream recordings with near-identical motion.
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-skip_frame:v", "noref",
           "-i", str(path)]
    if has_audio:
        cmd += ["-map", "0:a:0", "-ac", "1", "-ar", str(AUDIO_SR), "-f", "s16le", "-y", str(audio_out)]
    cmd += [
        "-map", "0:v:0",
        "-vf", f"fps={ANALYSIS_FPS},scale={ANALYSIS_W}:{ANALYSIS_H}:flags=area,format=gray",
        "-f", "rawvideo", "pipe:1",
    ]
    frame_bytes = ANALYSIS_W * ANALYSIS_H
    batch = frame_bytes * 256
    expected_frames = max(1.0, duration * ANALYSIS_FPS)
    log_path = audio_out.with_suffix(".log")

    with open(log_path, "wb") as log:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=log)
        assert proc.stdout is not None
        frames_seen = 0
        leftover = b""
        try:
            while True:
                chunk = proc.stdout.read(batch)
                if not chunk:
                    break
                data = leftover + chunk
                usable = len(data) - (len(data) % frame_bytes)
                leftover = data[usable:]
                if usable:
                    on_frames(data[:usable])
                    frames_seen += usable // frame_bytes
                    if progress:
                        progress(min(1.0, frames_seen / expected_frames))
        finally:
            proc.stdout.close()
            code = proc.wait()
    if code != 0:
        err = log_path.read_text(errors="replace").strip()[-500:]
        raise FFmpegError(f"ffmpeg failed while decoding: {err}")


def extract_frame(path: Path, t: float, out: Path, width: int = 640) -> Path:
    cmd = [
        "ffmpeg", "-hide_banner", "-nostdin", "-v", "error",
        "-ss", f"{max(0.0, t):.3f}", "-i", str(path),
        "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "3", "-y", str(out),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0 or not out.exists():
        raise FFmpegError(f"Could not extract frame at {t:.1f}s: {proc.stderr.strip()[:300]}")
    return out


# ------------------------------------------------------------------ rendering


def run_with_progress(cmd: list[str], duration: float, progress: ProgressFn | None,
                      log_path: Path) -> None:
    """Run an ffmpeg command that was given ``-progress pipe:1``."""
    with open(log_path, "wb") as log:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=log, text=True)
        assert proc.stdout is not None
        for line in proc.stdout:
            key, _, value = line.strip().partition("=")
            if key == "out_time_us" and progress and duration > 0:
                try:
                    progress(min(1.0, max(0.0, int(value) / 1e6 / duration)))
                except ValueError:
                    pass
        code = proc.wait()
    if code != 0:
        err = log_path.read_text(errors="replace").strip()[-800:]
        raise FFmpegError(f"ffmpeg failed while rendering: {err}")
