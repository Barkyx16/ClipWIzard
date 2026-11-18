# Tuning highlight detection

The detector has only been tuned on synthetic test footage so far. Once you have real GTA 6 recordings, this page
explains what to adjust if the results are off.

## How a highlight is chosen

1. Each recording is reduced to four signals sampled 4 times a second (`backend/app/analysis/signals.py`):
   - **loudness**
   - **onsets** (sharp, gunfire-like transients)
   - **motion** (frame difference)
   - **loudness jumps** (sudden booms)
2. Each signal is compared with the recording's own **2-minute rolling baseline**, so a loud stream or constant radio
   music raises the bar instead of flagging everything.
3. The signals are combined into one **excitement** curve (`highlights.py`, `compute_features`):

   ```python
   exc = 1.0 * loud_z + 0.9 * onset_z + 0.6 * motion_z + 0.6 * jump_term   # with audio
   exc = 1.6 * motion_z                                                      # silent videos
   ```

4. Peaks above a threshold become clips. Each clip grows to cover the surrounding action, then gets 3 s of build-up
   and 2 s of reaction (`_grow_window`).
5. A label is picked from the signal mix (`_summarize`), and Claude, if enabled, renames and re-scores it.

## Symptoms and fixes

| What you see | Try |
| --- | --- |
| Too many boring clips | Lower **Sensitivity** in the upload card. In code, raise `floor` / `pct` in `detect_highlights`. |
| Missing obvious moments | Raise **Sensitivity**. In code, lower `floor` (absolute minimum excitement). |
| Car radio or music gets clipped | Lower the onset weight (`0.9 * onset_z`) or raise the onset threshold in `signals.py` (`e_db - recent > 10.0`, try 12-14 dB). |
| Streamer talking triggers clips | Lower the loudness weight (`1.0 * loud_z`) relative to onsets and motion. |
| Chases are missed | Raise the motion weight (`0.6 * motion_z`). |
| Clips start too late or end too early | Change the padding in `_grow_window` (`- 3.0` build-up, `+ 2.0` reaction). |
| Clips are cut mid-action | Lower `level = exc[peak] * 0.35` (e.g. 0.25) so windows grow further around the peak. |
| Wrong labels | Adjust the rules in `_summarize` (onset rate ≥ 3/s means Shootout, sustained motion means Chase, a 15 dB jump means Big Impact). |
| Smart crop is jittery or slow | `MAX_PAN_PER_SEC` and `SMOOTH_SECONDS` in `smartcrop.py`. |

## A tuning loop that works

1. Collect 3-5 real recordings and note, by hand, the timestamps of the moments you'd post.
2. Run detection without the UI:

   ```bash
   cd backend
   ../.venv/bin/python - <<'PY'
   from pathlib import Path
   from app.media.ffmpeg import probe, decode_for_analysis
   from app.analysis.signals import MotionAccumulator, build_signals
   from app.analysis.highlights import detect_highlights, DetectOptions
   src = Path("my-session.mp4")
   info = probe(src); acc = MotionAccumulator()
   decode_for_analysis(src, Path("/tmp/a.raw"), info.has_audio, info.duration, acc.feed)
   sig = build_signals(Path("/tmp/a.raw"), acc, info.has_audio)
   for c in detect_highlights(sig, info.duration, DetectOptions())[1]:
       print(f"{c.start:7.1f}-{c.end:7.1f}  peak {c.peak:7.1f}  {c.score:5.1f}  {c.category}")
   PY
   ```

3. Compare with your list, adjust one number at a time, and rerun.
4. When you're happy, turn one of the recordings into a test like `tests/test_detection.py` so the tuning stays put.
