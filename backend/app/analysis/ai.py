"""Optional Claude-powered enrichment of highlight candidates.

For each candidate we send a handful of keyframes plus the signal summary to
Claude and ask for a title, a GTA-specific category, a hype score, a social
caption and hashtags. It also tells us when a "highlight" is really a menu,
map or loading screen so we can demote it.

Everything here is best-effort: if the API is unavailable or a request fails,
the heuristic results are kept as-is.
"""

from __future__ import annotations

import base64
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from ..config import get_settings
from ..media.ffmpeg import FFmpegError, extract_frame
from .highlights import Candidate

log = logging.getLogger(__name__)

AI_CATEGORIES = [
    "Shootout",
    "Police Chase",
    "Car Chase",
    "Explosion",
    "Car Crash",
    "Stunt",
    "Heist",
    "Wanted Escape",
    "Funny Moment",
    "Fail",
    "Clutch Play",
    "Scenic",
    "Hype Moment",
]

SYSTEM_PROMPT = """You are the clip editor behind ClipWizard, a tool that helps gamers turn long \
Grand Theft Auto VI gameplay recordings into short clips for TikTok, YouTube Shorts and \
Instagram Reels.

You will be shown a few frames sampled in order from one candidate clip, plus audio/motion \
measurements from an automatic detector. Judge what is happening and how share-worthy it is.

Guidelines:
- Describe only what the frames and signals support. Do not invent story details you cannot see.
- Titles are short, punchy and written like a gamer would post them (max ~60 characters, \
no hashtags, at most one emoji).
- The caption is one or two sentences for the post body.
- hype_score is 0-100: 85+ is a genuinely viral-worthy moment, 50 is decent, under 25 is filler.
- Set is_gameplay to false for menus, maps, phone screens, loading screens, cutscene black \
bars with nothing happening, or desktop/streaming overlays without gameplay.
- Hashtags: 3 to 6, lowercase, without the # symbol."""

RESULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "is_gameplay": {"type": "boolean"},
        "category": {"type": "string", "enum": AI_CATEGORIES},
        "title": {"type": "string"},
        "description": {"type": "string"},
        "caption": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
        "hype_score": {"type": "integer"},
    },
    "required": [
        "is_gameplay", "category", "title", "description", "caption", "hashtags", "hype_score",
    ],
    "additionalProperties": False,
}


def _fmt_ts(seconds: float) -> str:
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _sample_times(c: Candidate, count: int = 5) -> list[float]:
    """Frames spread across the clip, with one placed right on the peak."""
    span = max(0.5, c.end - c.start)
    times = [c.start + span * (i + 0.5) / count for i in range(count)]
    closest = min(range(count), key=lambda i: abs(times[i] - c.peak))
    times[closest] = c.peak
    return sorted(times)


def _frames_b64(video_path: Path, c: Candidate, work: Path, idx: int) -> list[tuple[float, str]]:
    out: list[tuple[float, str]] = []
    for j, t in enumerate(_sample_times(c)):
        jpg = work / f"ai_{idx}_{j}.jpg"
        try:
            extract_frame(video_path, t, jpg, width=640)
        except FFmpegError:
            continue
        out.append((t, base64.standard_b64encode(jpg.read_bytes()).decode("ascii")))
        jpg.unlink(missing_ok=True)
    return out


def _enrich_one(client: Any, video_path: Path, c: Candidate, work: Path, idx: int) -> dict[str, Any] | None:
    import anthropic

    frames = _frames_b64(video_path, c, work, idx)
    if not frames:
        return None
    content: list[dict[str, Any]] = []
    for t, data in frames:
        content.append({"type": "text", "text": f"Frame at {_fmt_ts(t)}" + (" (peak)" if t == c.peak else "")})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}})
    content.append({
        "type": "text",
        "text": (
            f"Candidate clip {_fmt_ts(c.start)}-{_fmt_ts(c.end)} ({c.duration:.0f}s), peak at {_fmt_ts(c.peak)}.\n"
            f"Detector guess: {c.category}.\n"
            f"Signals (0-1 relative to the rest of the recording): audio={c.signals.get('audio')}, "
            f"gunfire-like transients={c.signals.get('gunfire')}, motion={c.signals.get('motion')}; "
            f"biggest sudden loudness jump={c.signals.get('impact_db')} dB.\n"
            "Return the JSON for this clip."
        ),
    })

    settings = get_settings()
    try:
        response = client.beta.messages.create(
            model=settings.claude_model,
            max_tokens=4000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
            output_config={
                "effort": settings.claude_effort,
                "format": {"type": "json_schema", "schema": RESULT_SCHEMA},
            },
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.RateLimitError as e:
        log.warning("Claude rate limited while enriching clip %s: %s", idx, e)
        return None
    except anthropic.APIStatusError as e:
        log.warning("Claude API error %s while enriching clip %s: %s", e.status_code, idx, e)
        return None
    except anthropic.APIConnectionError as e:
        log.warning("Could not reach Claude while enriching clip %s: %s", idx, e)
        return None

    if response.stop_reason == "refusal":
        log.info("Claude declined to describe clip %s", idx)
        return None
    if response.stop_reason == "max_tokens":
        log.warning("Claude response truncated for clip %s", idx)
        return None
    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        log.warning("Claude returned invalid JSON for clip %s", idx)
        return None
    return data


def enrich(video_path: Path, cands: list[Candidate], work: Path,
           progress: Callable[[float], None] | None = None) -> dict[int, dict[str, Any]]:
    """Returns {candidate index: ai result} for the candidates that succeeded."""
    settings = get_settings()
    if not settings.ai_enabled or not cands:
        return {}
    try:
        import anthropic
    except ImportError:  # pragma: no cover - dependency is in requirements
        log.warning("anthropic package missing; skipping AI enrichment")
        return {}

    client = anthropic.Anthropic(max_retries=3)
    targets = list(range(min(len(cands), settings.ai_max_highlights)))
    results: dict[int, dict[str, Any]] = {}
    done = 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {i: pool.submit(_enrich_one, client, video_path, cands[i], work, i) for i in targets}
        for i, fut in futures.items():
            try:
                res = fut.result()
            except Exception:  # never let enrichment kill the analysis
                log.exception("AI enrichment crashed for clip %s", i)
                res = None
            if res:
                results[i] = res
            done += 1
            if progress:
                progress(done / len(targets))
    return results


def clean_hashtags(tags: list[str]) -> list[str]:
    out = []
    for t in tags:
        t = "".join(ch for ch in t.strip().lstrip("#").lower() if ch.isalnum() or ch == "_")
        if t and t not in out:
            out.append(t)
    return out[:6]
