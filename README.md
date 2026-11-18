# ClipWizard

[![CI](https://github.com/Barkyx16/ClipWIzard/actions/workflows/ci.yml/badge.svg)](https://github.com/Barkyx16/ClipWIzard/actions/workflows/ci.yml)

**AI clipping for GTA 6 creators.** Upload a gameplay recording or paste a Twitch/YouTube VOD link. ClipWizard finds
the shootouts, explosions, crashes, chases and hype moments, ranks them, and exports vertical clips with captions,
ready for TikTok, YouTube Shorts and Instagram Reels.

> ClipWizard is a fan-made tool. It is not affiliated with or endorsed by Rockstar Games or Take-Two Interactive.
> Grand Theft Auto is a trademark of its respective owner.

## Features

**Finding the moments**
- **Highlight detection** that works on any recording, with no game integration needed. It looks for:
  - loudness spikes (yelling, sirens, explosions)
  - gunfire-like transient bursts and impacts
  - motion intensity (driving, chaos)
  - sudden "boom" jumps in loudness

  Every signal is measured against the recording's own rolling baseline.
- **Smart clip windows.** Each clip keeps the build-up before the peak and the reaction after, avoids starting on a
  scene cut, and never overlaps another clip.
- **AI titles and captions (optional).** Claude looks at keyframes and writes a title, a GTA-specific category, a hype
  score, a post caption and hashtags. It also demotes menus, maps and loading screens.
- **Import from a link.** YouTube, Twitch, Kick, Medal, Streamable, X, TikTok, Reddit, Vimeo, or a direct video-file
  link.
- **Resumable uploads.** Multi-GB files upload in chunks that retry on bad connections. Picking the same file again
  resumes where the last attempt stopped. Drop up to 10 recordings at once.
- **Timeline previews.** Hover the heat-map timeline to see any moment, which makes long VODs quick to scan.

**Making the clips**
- **Formats:**
  - 9:16 blurred fill
  - 9:16 smart crop that pans to follow the action
  - 9:16 fixed crop
  - 9:16 facecam split (draw a box around your cam once; it's stacked above the gameplay)
  - 1:1 square
  - original 16:9
- **Auto captions.** Word-by-word, TikTok-style subtitles from voice chat and commentary, with the spoken word
  highlighted. Three styles (Bold, Neon, Clean) and adjustable height. **Review words** lets you fix misheard
  words before exporting.
- **Slow-mo instant replay.** The clip ends with a white flash and its peak moment replayed at half speed.
- **Even volume.** Exports are loudness-normalized to about -14 LUFS, the level TikTok, Shorts and Reels play at.
- **Burned-in title and channel-handle watermark.**
- **Montage builder.** Stitch the best moments into one compilation with crossfades, fades to black, slides or hard
  cuts.
- **Editor:**
  - heat-map timeline, looping preview, live crop preview
  - frame-accurate trim, plus saving your own ranges as highlights
  - keyboard shortcuts: <kbd>Space</kbd> play, <kbd>I</kbd>/<kbd>O</kbd> in/out, <kbd>←</kbd>/<kbd>→</kbd> seek,
    <kbd>J</kbd>/<kbd>L</kbd> ±10s, <kbd>[</kbd>/<kbd>]</kbd> previous/next highlight
- **Share links.** One click creates a private link to a finished clip that you can open on your phone to post, or send
  to a friend. Pasted into Discord, X or iMessage, the link shows a preview with the clip. Links can be revoked.
- **Download all.** Every finished clip of a session in one zip, and a **My clips** page listing every clip you've made.
- **Auto-export.** Tick it when uploading and the top 1-10 highlights render as soon as analysis finishes, in the format
  you last used. You get a desktop notification when a session is ready.

**Privacy**
- **Private workspaces.** Each browser gets its own anonymous workspace, and visitors only see their own uploads,
  clips and media files. The workspace key can be copied to open the same workspace on another device.

## Quick start

### Docker (easiest)

```bash
cp .env.example .env        # optional: add ANTHROPIC_API_KEY for AI titles
docker compose up --build
```

Open http://localhost:8000. The first export with captions downloads the speech model (about 150 MB), which is then
cached on the data volume.

Putting it on the internet? See **[docs/DEPLOY.md](docs/DEPLOY.md)** for a production setup with HTTPS.

### Local development

Requirements: Python 3.11+, Node 20+, and `ffmpeg` / `ffprobe` on your PATH.

```bash
make setup                  # venv + pip install + npm install
make backend                # API on :8000 (terminal 1)
make frontend               # UI on :5173 with hot reload (terminal 2)
```

Open http://localhost:5173. No gameplay handy? Run `make demo` to generate `demo.mp4`, a 90-second synthetic recording
with a shootout, an explosion and a car chase.

To serve the built UI from the backend (one port, the same way Docker does it), run `make build`, then `make backend`.

### Tests

```bash
make test                   # backend pytest suite + frontend type-check
```

## Configuration

All settings are environment variables. Put them in `.env` (see [`.env.example`](.env.example)).

| Variable | Default | What it does |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | none | Turns on AI titles, captions and screen filtering |
| `CLIPWIZARD_CLAUDE_MODEL` | `claude-opus-5-5` | Model used for enrichment |
| `CLIPWIZARD_CLAUDE_EFFORT` | `low` | Effort level per enrichment call (`low` to `max`) |
| `CLIPWIZARD_AI_MAX_HIGHLIGHTS` | `15` | Max highlights per video sent to Claude |
| `CLIPWIZARD_AI` | `on` | `off` disables AI even when a key is present |
| `CLIPWIZARD_WHISPER_MODEL` | `base` | Speech model for captions (`tiny`, `base`, `small`, `medium`…) |
| `CLIPWIZARD_WHISPER_DIR` | Hugging Face cache | Where the speech model is stored |
| `CLIPWIZARD_DATA_DIR` | `./data` | Uploads, thumbnails, renders and the SQLite database |
| `CLIPWIZARD_MAX_UPLOAD_MB` | `8192` | Upload and import size limit |
| `CLIPWIZARD_MAX_IMPORT_HOURS` | `6` | Longest VOD that can be imported from a link |
| `CLIPWIZARD_UPLOAD_CHUNK_MB` | `16` | Chunk size for resumable uploads |
| `CLIPWIZARD_RETENTION_DAYS` | `0` (keep forever) | Delete sessions idle for this many days. Set this on public servers |
| `CLIPWIZARD_MAX_ACTIVE_VIDEOS` | `3` | Videos one workspace can have processing at once (0 = unlimited) |
| `CLIPWIZARD_MAX_ACTIVE_RENDERS` | `12` | Clips one workspace can have rendering at once (0 = unlimited) |
| `CLIPWIZARD_WORKSPACE_QUOTA_GB` | `0` (unlimited) | Storage limit per workspace |
| `CLIPWIZARD_RATE_LIMIT_PER_MIN` / `_PER_HOUR` | `20` / `200` | Jobs one IP can start (uploads, imports, renders, transcripts); 0 = off |
| `CLIPWIZARD_TRUST_PROXY` | off | Set to `1` behind a reverse proxy so client IPs come from `X-Forwarded-For` |
| `CLIPWIZARD_PUBLIC_URL` | from the request | Public address (e.g. `https://clips.example.com`) used in share-link previews |
| `CLIPWIZARD_MAX_QUEUE` | `100` | When this many videos are waiting, new ones get a friendly "busy" message |
| `CLIPWIZARD_FFMPEG_STALL_SECONDS` | `180` | Kill an ffmpeg job that makes no progress for this long |
| `CLIPWIZARD_IMPORT_USE_PROXY` | off | Set to `1` if the server must reach the internet through an HTTP proxy |
| `CLIPWIZARD_WORKERS` | `2` | Background jobs that run in parallel |
| `CLIPWIZARD_FONT` | DejaVu Sans Bold | TTF used for burned-in titles |
| `CLIPWIZARD_CORS_ORIGINS` | none | Only needed if the UI is hosted on another origin |

For local testing without the speech model, `CLIPWIZARD_FAKE_TRANSCRIBE=1` returns a canned transcript. Never set it in
production.

AI enrichment sends about five 640px keyframes per highlight to the Anthropic API, so it costs a little per video.
Lower `CLIPWIZARD_AI_MAX_HIGHLIGHTS` to cap the cost.

### Restyling

Every color and font in the UI comes from [`frontend/src/theme.css`](frontend/src/theme.css). Change the values there
to rebrand the whole site. If you switch fonts, install the matching `@fontsource` package and update the imports at
the top of `frontend/src/main.tsx`.

## How it works

```
upload / link ─► ffprobe ─► one ffmpeg decode (non-reference frames skipped)
   ├─► 8 kHz mono audio ─► loudness, gunfire-like transients, loudness jumps
   └─► 64×36 gray @ 4 fps ─► motion, brightness, scene cuts, where the action is (for smart crop)
─► excitement curve (robust z-scores vs a 2-minute rolling baseline)
─► peak picking ─► grow, pad and snap windows ─► de-overlap ─► score and label
─► (optional) Claude vision: title, category, caption, hashtags, hype score, gameplay check
─► editor ─► render: crop/fill/facecam layout + title + watermark + captions ─► MP4 (H.264/AAC, faststart)
```

Analysis speed on a 4-core machine is about 17× realtime for 1080p60 footage (a 3-hour VOD takes roughly 10 minutes),
and memory use stays flat regardless of length.

| Path | Purpose |
| --- | --- |
| `backend/app/main.py` | FastAPI routes, media access control, SPA hosting |
| `backend/app/pipeline.py` | Analysis, import and render jobs |
| `backend/app/workspace.py` | Anonymous private workspaces |
| `backend/app/analysis/signals.py` | Audio and motion feature extraction |
| `backend/app/analysis/highlights.py` | Highlight detection, scoring, labelling |
| `backend/app/analysis/smartcrop.py` | Camera path for the smart vertical crop |
| `backend/app/analysis/ai.py` | Claude enrichment (structured JSON output) |
| `backend/app/media/render.py` | Layouts, titles, watermark, captions, montage joining |
| `backend/app/media/captions.py` | Speech-to-text and word-by-word caption styling |
| `backend/app/media/importer.py` | Link imports (yt-dlp + safe direct downloader) |
| `backend/app/retention.py` | Optional cleanup of old sessions |
| `frontend/src/pages/ProjectPage.tsx` | Player, timeline, highlights, editor and exports |

### API

| Method | Path | |
| --- | --- | --- |
| `GET` | `/api/health` | Server status and which optional features are available |
| `POST` | `/api/uploads` → `PUT /api/uploads/{id}?offset=` → `POST /api/uploads/{id}/complete` | Resumable upload |
| `POST` | `/api/videos?filename=…` | Single-request upload (raw body) |
| `POST` | `/api/videos/import` | Import from a link |
| `GET` | `/api/videos` · `/api/videos/{id}` · `/api/videos/{id}/timeline` | List, details, timeline curves |
| `POST` | `/api/videos/{id}/reanalyze` | Re-scan with new settings |
| `PUT` | `/api/videos/{id}/layout` | Save the facecam rectangle |
| `POST` / `PATCH` / `DELETE` | `/api/videos/{id}/highlights` · `/api/highlights/{id}` | Custom, edited and removed highlights |
| `PATCH` | `/api/videos/{id}` | Rename a session |
| `POST` | `/api/videos/{id}/clips` · `/export-all` · `/montage` | Render a clip, the top N, or a montage |
| `POST` / `GET` | `/api/videos/{id}/transcripts` · `/api/transcripts/{id}` | Transcribe a range for caption review |
| `GET` / `DELETE` | `/api/clips/{id}` · `/api/clips/{id}/download` | Clip status, download, delete |
| `GET` | `/api/videos/{id}/clips.zip` | All finished clips in one zip |
| `POST` / `DELETE` | `/api/clips/{id}/share` | Turn a share link on or off |
| `GET` / `POST` | `/api/workspace` | Show the workspace key, or open another workspace |

All `/api` and `/media` routes are scoped to the caller's workspace cookie. `/s/{token}` and `/share/{token}/…` are
the only public routes, and they only exist while a clip is shared.

## Before going big

This MVP runs on a single server. Before a large public launch, you'll want:

- **Accounts** (email or Discord/Twitch login) on top of the anonymous workspaces, plus storage quotas per user.
- **A real job queue** (RQ, Celery or Arq) and object storage (S3 or R2) to scale past one machine. Background jobs
  currently run inside the API process.
- **Sandboxed media processing.** ffmpeg and yt-dlp handle untrusted input, so run them with tight CPU, memory and
  network limits.
- **Retention.** Set `CLIPWIZARD_RETENTION_DAYS`.

## Roadmap ideas

- Reaction detection from facecam audio (laughs, screams) as an extra highlight signal
- Per-game tuning once real GTA 6 footage is available
- Direct publishing to TikTok, YouTube Shorts and Instagram
