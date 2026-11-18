"""Automatic, TikTok-style captions.

1. The clip's audio is transcribed with faster-whisper (word timestamps).
2. Words are grouped into short punchy phrases.
3. An ASS subtitle file is written where the word being spoken is
   highlighted, and burned in by ffmpeg/libass while rendering.

faster-whisper is optional: if it isn't installed, or the model can't be
downloaded, clips still render, just without captions.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

_model = None
_model_lock = threading.Lock()
_run_lock = threading.Lock()


@dataclass
class Word:
    start: float
    end: float
    text: str


class CaptionError(RuntimeError):
    pass


def available() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


def _get_model():
    global _model
    with _model_lock:
        if _model is None:
            from faster_whisper import WhisperModel

            name = os.environ.get("CLIPWIZARD_WHISPER_MODEL", "base")
            root = os.environ.get("CLIPWIZARD_WHISPER_DIR")
            try:
                _model = WhisperModel(name, device="cpu", compute_type="int8", download_root=root)
            except Exception as e:  # network / disk problems while fetching the model
                raise CaptionError(
                    f"couldn't download the speech model '{name}'. Make sure the server can reach "
                    f"huggingface.co ({type(e).__name__})"
                ) from e
        return _model


def transcribe(src: Path, start: float, end: float, work: Path) -> list[Word]:
    """Words spoken in [start, end], with times relative to the clip start."""
    if not available():
        raise CaptionError("Auto captions need the faster-whisper package")
    work.mkdir(parents=True, exist_ok=True)
    wav = work / "speech.wav"
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", "-ss", f"{start:.3f}",
         "-i", str(src), "-t", f"{max(0.5, end - start):.3f}", "-vn", "-ac", "1", "-ar", "16000",
         str(wav)],
        capture_output=True, text=True, timeout=600,
    )
    if proc.returncode != 0 or not wav.exists():
        raise CaptionError("Could not extract audio for captions")
    model = _get_model()
    with _run_lock:
        segments, _info = model.transcribe(str(wav), word_timestamps=True, vad_filter=True,
                                           beam_size=1, condition_on_previous_text=False)
        words = [
            Word(float(w.start), float(w.end), w.word.strip())
            for seg in segments
            for w in (seg.words or [])
            if w.word and w.word.strip()
        ]
    wav.unlink(missing_ok=True)
    return words


# ------------------------------------------------------------------ layout


def group_phrases(words: list[Word], max_words: int = 3, max_chars: int = 18,
                  max_gap: float = 0.45) -> list[list[Word]]:
    """Short phrases: break on pauses, punctuation, length."""
    phrases: list[list[Word]] = []
    cur: list[Word] = []
    for w in words:
        if cur:
            gap = w.start - cur[-1].end
            chars = sum(len(x.text) + 1 for x in cur) + len(w.text)
            ends_sentence = cur[-1].text[-1:] in ".!?,;:"
            if len(cur) >= max_words or chars > max_chars or gap > max_gap or ends_sentence:
                phrases.append(cur)
                cur = []
        cur.append(w)
    if cur:
        phrases.append(cur)
    return phrases


def _ass_time(t: float) -> str:
    t = max(0.0, t)
    cs = int(round(t * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _ass_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", " ")


def _ass_color(hex_rgb: str) -> str:
    """#RRGGBB -> ASS &H00BBGGRR."""
    h = hex_rgb.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H00{b}{g}{r}".upper()


def build_ass(words: list[Word], out_w: int, out_h: int, duration: float,
              highlight: str = "#FFD84D", position: float = 0.70, uppercase: bool = True,
              font: str = "DejaVu Sans") -> str:
    """ASS script with one event per spoken word; that word is highlighted."""
    vertical = out_h > out_w
    size = int(out_w * (0.085 if vertical else 0.05))
    margin_v = int(out_h * (1 - position))
    hl = _ass_color(highlight)
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {out_w}",
        f"PlayResY: {out_h}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Caption,{font},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,"
        f"{max(3, size // 12)},{max(1, size // 30)},2,{int(out_w * 0.08)},{int(out_w * 0.08)},{margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for phrase in group_phrases(words):
        texts = [_ass_escape(w.text.upper() if uppercase else w.text) for w in phrase]
        for i, w in enumerate(phrase):
            start = w.start
            nxt = phrase[i + 1].start if i + 1 < len(phrase) else max(w.end, w.start + 0.25)
            end = min(duration, max(nxt, start + 0.08))
            if start >= duration:
                break
            parts = [
                (f"{{\\c{hl}\\fscx108\\fscy108}}{t}{{\\c&H00FFFFFF&\\fscx100\\fscy100}}" if j == i else t)
                for j, t in enumerate(texts)
            ]
            lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Caption,,0,0,0,,{' '.join(parts)}")
    return "\n".join(lines) + "\n"


def transcript_text(words: list[Word]) -> str:
    return " ".join(w.text for w in words).strip()
