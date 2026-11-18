import subprocess

import numpy as np

from app.media.captions import Word, _ass_time, build_ass, group_phrases, transcript_text
from app.media.ffmpeg import probe
from app.media.render import RenderOptions, render_clip

WORDS = [
    Word(0.2, 0.5, "No"), Word(0.55, 0.8, "way"), Word(0.85, 1.2, "bro,"),
    Word(1.25, 1.5, "he"), Word(1.55, 1.9, "actually"), Word(2.6, 3.0, "survived!"),
]


def test_group_phrases_breaks_on_punctuation_pauses_and_length():
    phrases = [[w.text for w in p] for p in group_phrases(WORDS)]
    assert phrases == [["No", "way", "bro,"], ["he", "actually"], ["survived!"]]


def test_ass_time_format():
    assert _ass_time(0) == "0:00:00.00"
    assert _ass_time(61.234) == "0:01:01.23"
    assert _ass_time(3725.5) == "1:02:05.50"


def test_build_ass_highlights_each_word():
    ass = build_ass(WORDS, 1080, 1920, 3.5, highlight="#FFD84D")
    events = [line for line in ass.splitlines() if line.startswith("Dialogue:")]
    assert len(events) == len(WORDS)
    assert "PlayResX: 1080" in ass and "PlayResY: 1920" in ass
    # The first event highlights "NO" (ASS colours are BGR).
    assert "{\\c&H004DD8FF" in events[0] and "NO" in events[0]
    assert events[0].split(",")[1] == "0:00:00.20"
    assert transcript_text(WORDS).startswith("No way bro,")


def test_build_ass_escapes_override_braces():
    ass = build_ass([Word(0, 1, "{\\b1}hack")], 1080, 1920, 2)
    assert "{\\b1}" not in ass.split("[Events]")[1].replace("{\\c", "").replace("{\\fscx", "")


def _frame(video, t):
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(video), "-frames:v", "1",
         "-vf", "scale=270:480,format=gray", "-f", "rawvideo", "pipe:1"],
        capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(480, 270).astype(np.float32)


def test_captions_are_burned_in(demo_video, tmp_path):
    ass = tmp_path / "c.ass"
    ass.write_text(build_ass(WORDS, 1080, 1920, 3.5), encoding="utf-8")
    with_caps = tmp_path / "caps.mp4"
    without = tmp_path / "plain.mp4"
    render_clip(demo_video, with_caps, 10.0, 13.5, 320, 180, 25.0, True,
                RenderOptions(aspect="vertical_smart", captions_ass=ass, quality="fast"), tmp_path / "w1")
    render_clip(demo_video, without, 10.0, 13.5, 320, 180, 25.0, True,
                RenderOptions(aspect="vertical_smart", quality="fast"), tmp_path / "w2")
    assert probe(with_caps).height == 1920
    diff = np.abs(_frame(with_caps, 0.7) - _frame(without, 0.7))
    # Captions sit just above 72% of the height; the rest of the frame is unchanged.
    assert diff[300:345].mean() > 15
    assert diff[:250].mean() < 3
