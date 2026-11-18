"""Runtime configuration, read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("CLIPWIZARD_DATA_DIR", "./data")).resolve()
    )
    max_upload_mb: int = field(
        default_factory=lambda: int(os.environ.get("CLIPWIZARD_MAX_UPLOAD_MB", "8192"))
    )
    workers: int = field(default_factory=lambda: int(os.environ.get("CLIPWIZARD_WORKERS", "2")))

    # AI (Claude) settings. AI enrichment turns on automatically when an
    # Anthropic credential is present, unless CLIPWIZARD_AI=off.
    ai_requested: bool = field(default_factory=lambda: _env_bool("CLIPWIZARD_AI", True))
    claude_model: str = field(
        default_factory=lambda: os.environ.get("CLIPWIZARD_CLAUDE_MODEL", "claude-opus-5-5")
    )
    claude_effort: str = field(
        default_factory=lambda: os.environ.get("CLIPWIZARD_CLAUDE_EFFORT", "low")
    )
    ai_max_highlights: int = field(
        default_factory=lambda: int(os.environ.get("CLIPWIZARD_AI_MAX_HIGHLIGHTS", "15"))
    )

    # Abuse limits per workspace (0 = unlimited).
    max_active_videos: int = field(
        default_factory=lambda: int(os.environ.get("CLIPWIZARD_MAX_ACTIVE_VIDEOS", "3"))
    )
    max_active_renders: int = field(
        default_factory=lambda: int(os.environ.get("CLIPWIZARD_MAX_ACTIVE_RENDERS", "12"))
    )
    workspace_quota_gb: float = field(
        default_factory=lambda: float(os.environ.get("CLIPWIZARD_WORKSPACE_QUOTA_GB", "0"))
    )

    # Optional path to a TTF font for burned-in titles.
    font_path: str | None = field(default_factory=lambda: os.environ.get("CLIPWIZARD_FONT"))

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @property
    def uploads_dir(self) -> Path:
        return self.media_dir / "uploads"

    @property
    def thumbs_dir(self) -> Path:
        return self.media_dir / "thumbs"

    @property
    def clips_dir(self) -> Path:
        return self.media_dir / "clips"

    @property
    def work_dir(self) -> Path:
        return self.data_dir / "work"

    @property
    def analysis_dir(self) -> Path:
        return self.data_dir / "analysis"

    @property
    def partial_dir(self) -> Path:
        """In-progress chunked uploads."""
        return self.data_dir / "partial"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "clipwizard.sqlite3"

    @property
    def ai_enabled(self) -> bool:
        has_credential = bool(
            os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        )
        return self.ai_requested and has_credential

    def ensure_dirs(self) -> None:
        for d in (self.uploads_dir, self.thumbs_dir, self.clips_dir, self.work_dir,
                  self.analysis_dir, self.partial_dir):
            d.mkdir(parents=True, exist_ok=True)


def load_dotenv() -> None:
    """Load KEY=VALUE pairs from a .env file (cwd or repo root) without
    overriding variables that are already set."""
    for candidate in (Path.cwd() / ".env", Path(__file__).resolve().parents[2] / ".env"):
        if not candidate.is_file():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip().removeprefix("export ").strip(), value.strip().strip("'\"")
            if key and value:
                os.environ.setdefault(key, value)
        return


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        if not os.environ.get("CLIPWIZARD_SKIP_DOTENV"):
            load_dotenv()
        _settings = Settings()
        _settings.ensure_dirs()
    return _settings


def reset_settings() -> None:
    """Used by tests to pick up a changed environment."""
    global _settings
    _settings = None
