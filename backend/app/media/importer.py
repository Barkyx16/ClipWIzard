"""Import a recording from a link instead of uploading it.

Two paths:

* Known platforms (YouTube, Twitch, Kick, Medal, ...) go through yt-dlp,
  restricted to those platforms' extractors (no generic "any web page"
  extractor) and to single videos.
* Direct links to a video file are fetched by a small downloader that only
  talks to public IP addresses and re-checks every redirect, so the server
  can't be used to reach internal services.
"""

from __future__ import annotations

import ipaddress
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Literal

ProgressFn = Callable[[float], None]

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}

# host suffix -> friendly name
PLATFORMS: dict[str, str] = {
    "youtube.com": "YouTube",
    "youtu.be": "YouTube",
    "twitch.tv": "Twitch",
    "kick.com": "Kick",
    "medal.tv": "Medal",
    "streamable.com": "Streamable",
    "x.com": "X",
    "twitter.com": "X",
    "tiktok.com": "TikTok",
    "reddit.com": "Reddit",
    "v.redd.it": "Reddit",
    "vimeo.com": "Vimeo",
}

YTDLP_EXTRACTORS = [
    "youtube", "youtube:clip", "YoutubeYtBe",
    "twitch:vod", "twitch:clips",
    "kick:vod", "kick:clip",
    "MedalTV", "Streamable", "twitter", "TikTok", "Reddit", "vimeo",
]


class ImportFailed(RuntimeError):
    """A user-facing reason the import can't go ahead."""


def _allow_private() -> bool:
    return os.environ.get("CLIPWIZARD_ALLOW_PRIVATE_URLS") == "1"


def max_import_seconds() -> float:
    return float(os.environ.get("CLIPWIZARD_MAX_IMPORT_HOURS", "6")) * 3600


def platform_for(host: str) -> str | None:
    host = host.lower().rstrip(".")
    for suffix, name in PLATFORMS.items():
        if host == suffix or host.endswith("." + suffix):
            return name
    return None


def classify(url: str) -> tuple[Literal["platform", "direct"], str]:
    """Validate a pasted link. Returns (kind, friendly source name)."""
    url = url.strip()
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError as e:
        raise ImportFailed("That doesn't look like a valid link") from e
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ImportFailed("Paste a full http(s):// link")
    if parts.username or parts.password:
        raise ImportFailed("Links with passwords in them aren't supported")
    name = platform_for(parts.hostname)
    if name:
        return "platform", name
    if Path(parts.path).suffix.lower() in VIDEO_EXTENSIONS:
        return "direct", parts.hostname
    raise ImportFailed(
        "Paste a link from YouTube, Twitch, Kick, Medal, Streamable, X, TikTok, Reddit or Vimeo, "
        "or a direct link to an .mp4/.mov/.mkv/.webm file"
    )


def display_name(url: str) -> str:
    parts = urllib.parse.urlsplit(url.strip())
    name = platform_for(parts.hostname or "")
    tail = Path(parts.path).name or parts.hostname or "video"
    return f"{name} · {tail}"[:120] if name else tail[:120]


# ------------------------------------------------------------------ direct links


def _check_public(host: str, port: int | None) -> None:
    if _allow_private():
        return
    try:
        infos = socket.getaddrinfo(host, port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise ImportFailed(f"Couldn't find the server '{host}'") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global or ip.is_multicast:
            raise ImportFailed("That link points to a private network address")


class _SafeRedirects(urllib.request.HTTPRedirectHandler):
    max_redirections = 5

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        parts = urllib.parse.urlsplit(newurl)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ImportFailed("The link redirected somewhere unsupported")
        _check_public(parts.hostname, parts.port)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download_direct(url: str, dest: Path, limit_bytes: int,
                    progress: ProgressFn | None = None) -> Path:
    parts = urllib.parse.urlsplit(url)
    _check_public(parts.hostname or "", parts.port)
    opener = urllib.request.build_opener(_SafeRedirects())
    req = urllib.request.Request(url, headers={"User-Agent": "ClipWizard/0.2 (+video import)"})
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with opener.open(req, timeout=30) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            if total and total > limit_bytes:
                raise ImportFailed("That video is larger than the upload limit")
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if ctype.startswith(("text/", "application/json")):
                raise ImportFailed("That link is a web page, not a video file")
            done = 0
            with open(tmp, "wb") as f:
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    done += len(chunk)
                    if done > limit_bytes:
                        raise ImportFailed("That video is larger than the upload limit")
                    f.write(chunk)
                    if progress and total:
                        progress(min(1.0, done / total))
    except urllib.error.HTTPError as e:
        tmp.unlink(missing_ok=True)
        raise ImportFailed(f"The server answered {e.code} {e.reason}") from e
    except urllib.error.URLError as e:
        tmp.unlink(missing_ok=True)
        if isinstance(e.reason, ImportFailed):
            raise e.reason from e
        raise ImportFailed(f"Couldn't download the video ({e.reason})") from e
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(dest)
    return dest


# ------------------------------------------------------------------ platforms


_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def download_platform(url: str, dest_stem: Path, limit_bytes: int,
                      progress: ProgressFn | None = None) -> tuple[Path, str | None]:
    """Download with yt-dlp. Returns (file path, video title)."""
    try:
        from yt_dlp import YoutubeDL
        from yt_dlp.utils import DownloadError
    except ImportError as e:
        raise ImportFailed("Importing from video sites needs the yt-dlp package") from e

    max_secs = max_import_seconds()

    def match_filter(info: dict, *, incomplete: bool = False) -> str | None:
        if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming"):
            return "Live streams can't be imported. Wait for the VOD"
        duration = info.get("duration")
        if duration and duration > max_secs:
            return f"That video is longer than {max_secs / 3600:g} hours"
        return None

    def hook(d: dict) -> None:
        if progress and d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                progress(min(1.0, d.get("downloaded_bytes", 0) / total))

    opts = {
        "outtmpl": str(dest_stem) + ".%(ext)s",
        "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]/b",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "allowed_extractors": [f"^{re.escape(n)}$" for n in YTDLP_EXTRACTORS],
        "max_filesize": limit_bytes,
        "match_filter": match_filter,
        "progress_hooks": [hook],
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "socket_timeout": 30,
        "retries": 3,
    }
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except DownloadError as e:
        msg = _ANSI.sub("", str(e)).replace("ERROR: ", "").strip()
        raise ImportFailed(msg[:300] or "The video couldn't be downloaded") from e
    if not info:
        raise ImportFailed("The video couldn't be downloaded")
    downloads = info.get("requested_downloads") or []
    path = Path(downloads[0]["filepath"]) if downloads else None
    if path is None or not path.exists():
        candidates = sorted(dest_stem.parent.glob(dest_stem.name + ".*"))
        path = next((c for c in candidates if not c.name.endswith(".part")), None)
    if path is None or not path.exists():
        raise ImportFailed("The download finished but no video file was found")
    return path, info.get("title")
