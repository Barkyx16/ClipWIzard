# Deploying ClipWizard

This guide puts ClipWizard on a single Linux server with HTTPS. Everything runs in Docker: the app, and
[Caddy](https://caddyserver.com) in front of it for certificates.

> These files haven't been test-deployed yet (the build environment had no Docker daemon). If something is off, the
> logs from `docker compose ... logs -f` will say what.

## 1. Pick a server

Video work is CPU-heavy. Rough guide:

| Users | Server |
| --- | --- |
| Just you and friends | 4 vCPU, 8 GB RAM |
| A small community | 8 vCPU, 16 GB RAM |

Disk is the other big one: uploads are stored until deleted. Budget around 2× the size of the recordings you expect
to keep, and set `CLIPWIZARD_RETENTION_DAYS` so old sessions clean themselves up.

Analysis runs at about 17× realtime per job on 4 cores for 1080p60, so a 3-hour VOD takes about 10 minutes.
`CLIPWIZARD_WORKERS` sets how many jobs run at once (default 2).

## 2. Point a domain at it

Create an `A` (and `AAAA` if you have IPv6) DNS record, for example `clips.example.com`, pointing at the server's IP.

## 3. Configure

On the server:

```bash
git clone https://github.com/Barkyx16/ClipWIzard.git
cd ClipWIzard
cp .env.example .env
```

Edit `.env`. Recommended for a public site:

```bash
ANTHROPIC_API_KEY=sk-ant-...          # optional: AI titles and captions
CLIPWIZARD_PUBLIC_URL=https://clips.example.com
CLIPWIZARD_RETENTION_DAYS=7           # delete sessions idle for a week
CLIPWIZARD_WORKSPACE_QUOTA_GB=20      # per-visitor storage cap
CLIPWIZARD_MAX_UPLOAD_MB=8192
CLIPWIZARD_WORKERS=2
```

Then replace `clips.example.com` in `deploy/Caddyfile` with your domain.

## 4. Start

```bash
docker compose -f deploy/docker-compose.prod.yml up -d --build
docker compose -f deploy/docker-compose.prod.yml logs -f clipwizard
```

Open `https://your-domain`. The first export with captions downloads the speech model (about 150 MB); after that it
is cached on the data volume.

## Updating

```bash
git pull
docker compose -f deploy/docker-compose.prod.yml up -d --build
```

Jobs that were running when the app restarts are picked up again automatically.

## Backups

Everything lives in the `clipwizard-data` volume: the SQLite database (`clipwizard.sqlite3`) plus uploads,
thumbnails and clips. To back it up:

```bash
docker run --rm -v deploy_clipwizard-data:/data -v "$PWD":/backup alpine \
  tar czf /backup/clipwizard-backup.tgz -C /data clipwizard.sqlite3 media/clips
```

(Uploads are usually too big to back up and can be re-uploaded.)

## Safety checklist for a public site

- Set `CLIPWIZARD_RETENTION_DAYS` and `CLIPWIZARD_WORKSPACE_QUOTA_GB`.
- Keep `CLIPWIZARD_TRUST_PROXY=1` only while the app sits behind Caddy (the compose file does this). Never expose port
  8000 directly with it on.
- The default per-IP limits (20 jobs/minute, 200/hour) and per-workspace limits are on. Lower them if you see abuse.
- Keep the server patched (`unattended-upgrades` on Ubuntu) and rebuild the image now and then for ffmpeg updates.
