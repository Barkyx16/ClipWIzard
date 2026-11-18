# ClipWizard

**AI clipping for GTA 6 creators.** Upload hours of gameplay or a full stream VOD. ClipWizard finds the
shootouts, explosions, crashes, chases and hype moments, ranks them, and exports vertical clips ready
for TikTok, YouTube Shorts and Instagram Reels.

> ClipWizard is a fan-made tool. It is not affiliated with or endorsed by Rockstar Games or Take-Two
> Interactive. Grand Theft Auto is a trademark of its respective owner.

## Features

- **Automatic highlight detection** that works on any recording, with no game integration needed:
  - loudness spikes (yelling, sirens, explosions)
  - transient bursts (gunfire, impacts)
  - motion intensity (high-speed driving, chaos on screen)
  - sudden loudness jumps ("boom" moments)
  - every signal is measured against the recording's own local baseline, so loud streams with music
    still work
- **Smart clip windows.** Clips grow to cover the whole action, keep some build-up before the peak and
  a beat after it, avoid starting on a scene cut, and never overlap.
- **AI titles and captions (optional).** With an Anthropic API key, Claude looks at keyframes from each
  highlight and writes a title, a GTA-specific category (Police Chase, Heist, Stunt...), a hype score,
  a post caption and hashtags. It also spots menus, maps and loading screens and pushes them down the
  ranking.
- **Editor.** A heat-map timeline of the whole session, a looping preview, frame-accurate trim,
  and a live crop preview.
- **Export formats:** 9:16 with blurred fill, 9:16 smart-crop (pick the crop position), 1:1, or the
  original 16:9. You can burn the title into the video.
- **Bulk export** of the top 5 highlights in one click.
- **Handles long sessions.** Uploads stream straight to disk, and each video is decoded once at low
  resolution for analysis, so memory stays flat for multi-hour files.

## Quick start

### Docker (easiest)

```bash
cp .env.example .env        # optional: add ANTHROPIC_API_KEY for AI titles
docker compose up --build
```

Open http://localhost:8000.

### Local development

Requirements: Python 3.11+, Node 20+, and `ffmpeg` / `ffprobe` on your PATH.

```bash
make setup                  # venv + pip install + npm install
make backend                # API on :8000 (terminal 1)
make frontend               # UI on :5173 with hot reload (terminal 2)
```

Open http://localhost:5173. No gameplay handy? Run `make demo` to generate `demo.mp4`, a 90-second
synthetic recording with a shootout, an explosion and a car chase.

To serve the built UI from the backend (single port, the same way Docker does it), run `make build`
and then `make backend`, and open http://localhost:8000.

### Tests

```bash
make test                   # backend pytest suite + frontend type-check
```

## Configuration

All settings are environment variables. Put them in `.env` (see [`.env.example`](.env.example)).

| Variable | Default | What it does |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | none | Turns on AI enrichment |
| `CLIPWIZARD_CLAUDE_MODEL` | `claude-opus-5-5` | Model used for enrichment |
| `CLIPWIZARD_CLAUDE_EFFORT` | `low` | Effort level for each enrichment call (`low` to `max`) |
| `CLIPWIZARD_AI_MAX_HIGHLIGHTS` | `15` | Max highlights per video sent to Claude |
| `CLIPWIZARD_AI` | `on` | Set to `off` to disable AI even when a key is present |
| `CLIPWIZARD_DATA_DIR` | `./data` | Uploads, thumbnails, renders and the SQLite database |
| `CLIPWIZARD_MAX_UPLOAD_MB` | `8192` | Upload size limit |
| `CLIPWIZARD_WORKERS` | `2` | Background jobs that run in parallel |
| `CLIPWIZARD_FONT` | DejaVu Sans Bold | TTF used for burned-in titles |
| `CLIPWIZARD_CORS_ORIGINS` | none | Only needed if the UI is hosted on a different origin |

AI enrichment sends about five 640px keyframes per highlight to the Anthropic API, so it costs a little
per video. Lower `CLIPWIZARD_AI_MAX_HIGHLIGHTS` to cap the cost.

## How it works

```
upload ─► ffprobe ─► single ffmpeg decode ─┬─► 8 kHz mono audio ─► loudness, gunfire-like transients, jumps
                                            └─► 64×36 gray @ 4fps ─► motion, brightness, scene cuts
          ─► fuse into an "excitement" curve (robust z-scores vs a 2-min rolling baseline)
          ─► peak picking ─► grow/pad/snap windows ─► de-overlap ─► score + label
          ─► (optional) Claude vision: title, category, caption, hashtags, hype score, gameplay check
          ─► thumbnails ─► ready for editing / export (ffmpeg, libx264 + AAC, faststart MP4)
```

| Path | Purpose |
| --- | --- |
| `backend/app/main.py` | FastAPI routes, static files, SPA hosting |
| `backend/app/pipeline.py` | Analysis and render jobs |
| `backend/app/analysis/signals.py` | Audio and motion feature extraction |
| `backend/app/analysis/highlights.py` | Highlight detection, scoring, labelling |
| `backend/app/analysis/ai.py` | Claude enrichment (structured JSON output) |
| `backend/app/media/render.py` | Vertical, square and landscape layouts, title overlay |
| `backend/app/demo.py` | Synthetic test footage generator |
| `frontend/src/pages/ProjectPage.tsx` | Player, timeline, highlights, editor and exports |

### API

| Method | Path | |
| --- | --- | --- |
| `GET` | `/api/health` | Server status, whether AI is enabled, upload limits |
| `POST` | `/api/videos?filename=…&length=short\|medium\|long&max_clips=12&sensitivity=0.5&use_ai=true` | Upload (raw request body) |
| `GET` | `/api/videos` · `/api/videos/{id}` | List, or get one with its highlights and clips |
| `GET` | `/api/videos/{id}/timeline` | Downsampled excitement, audio and motion curves |
| `POST` | `/api/videos/{id}/reanalyze` | Re-scan with new settings |
| `DELETE` | `/api/videos/{id}` | Delete the video and everything derived from it |
| `PATCH` | `/api/highlights/{id}` | Edit title, caption or range |
| `POST` | `/api/videos/{id}/clips` | Render a clip (`start`, `end`, `aspect`, `crop_x`, `title_overlay`, `title`) |
| `POST` | `/api/videos/{id}/export-all` | Render the top N highlights |
| `GET` | `/api/clips/{id}` · `/api/clips/{id}/download` | Clip status, MP4 download |

## Before going public

This is a working MVP built for a single server. Before opening it to the public, you'll want:

- **User accounts and auth.** Right now anyone who can reach the server sees every upload.
- **Rate limits and storage quotas**, plus cleanup of old uploads and renders.
- **A real job queue** (RQ, Celery or Arq) and object storage (S3 or R2) to scale past one machine.
  Background jobs currently run inside the API process.
- **Sandboxed media processing.** ffmpeg parses untrusted user files, so run it with tight resource limits.

## Roadmap ideas

- Speech-to-text captions (word-by-word subtitles) and reaction detection from facecam audio
- Smart vertical crop that follows the action instead of a fixed position
- Twitch and YouTube VOD import by URL
- Montage builder (stitch the top N clips with transitions and music)
- Direct publishing to TikTok, YouTube Shorts and Instagram
