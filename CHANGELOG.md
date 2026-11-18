# Changelog

## 0.2.0

### New
- **Import from a link**: YouTube, Twitch, Kick, Medal, Streamable, X, TikTok, Reddit, Vimeo, or a direct video-file
  URL.
- **Resumable chunked uploads** that survive dropped connections, and multi-file uploads (up to 10 at once).
- **Smart crop**: a 9:16 crop that pans to follow the action.
- **Facecam layout**: mark your webcam once and it's stacked above the gameplay.
- **Auto captions**: word-by-word subtitles (faster-whisper) in Bold, Neon or Clean style with adjustable height.
  **Review words** lets you fix misheard words before exporting.
- **Slow-mo instant replay** of the peak moment at the end of a clip.
- **Loudness normalization** to about -14 LUFS.
- **Montage builder** with crossfade, fade-to-black, slide or hard-cut transitions.
- **Auto-export** of the top 1-10 highlights when analysis finishes, and **desktop notifications** when a session is
  ready.
- **Share links** with rich previews in Discord, X and iMessage (revocable).
- **My clips** library across sessions, **Download all** as a zip, and **session renaming**.
- **Editor**: timeline hover previews, drag handles to trim, keyboard shortcuts, saving your own ranges as
  highlights, removing highlights, best/timeline sorting, a channel-handle watermark, and remembered format choices.
- **Private workspaces** per browser, with a key or a one-tap link to open them on another device.
- **Public-site protections**: per-workspace job and storage limits, per-IP rate limits, a global queue cap, and
  optional automatic cleanup of old sessions.
- Queue position, time-remaining estimate and tab-title progress while analyzing.
- FAQ, not-found page and session search.
- Production deployment guide (Docker + Caddy HTTPS).

### Fixed
- Titles or watermarks containing `%{...}` could hang a render worker (ffmpeg text expansion), and any `%` dropped
  the title.
- Every ffmpeg run now has a watchdog that kills stalled jobs.
- Direct-link imports were open to DNS-rebinding SSRF.
- A first-time visitor's parallel requests could create two workspaces and lose the upload.
- Clips could be queued on videos that weren't analyzed yet.
- Infinity/NaN in request bodies caused 500 errors.
- Videos could be deleted while their clips were still rendering.
- A double "complete upload" could create two sessions.
- Color contrast now meets WCAG AA.

### Under the hood
- About 25% faster analysis by skipping non-reference frames.
- Every UI color and font lives in `frontend/src/theme.css` for easy rebranding.
- CI runs the backend tests, the frontend format/type-check/build, and Playwright end-to-end tests.

## 0.1.0

First version: highlight detection (loudness, transients, motion, impacts), optional Claude titles and captions,
9:16 blur, crop, square and landscape exports with burned-in titles, editor with heat-map timeline, and Docker
setup.
