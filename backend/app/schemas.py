"""Request bodies, shared constants and types for the API."""

from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CaptionStyle = Literal["bold", "neon", "clean"]


Aspect = Literal[
    "landscape", "vertical_blur", "vertical_crop", "vertical_smart", "vertical_facecam", "square"
]


ALLOWED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".ts", ".flv"}


MAX_CLIP_SECONDS = 180


MAX_MONTAGE_SECONDS = 600


CHUNK_SIZE = int(float(os.environ.get("CLIPWIZARD_UPLOAD_CHUNK_MB", "16")) * 1024 * 1024)


MAX_CHUNK = 64 * 1024 * 1024


class ApiModel(BaseModel):
    """Base for request bodies: JSON allows Infinity/NaN, we don't."""

    model_config = ConfigDict(allow_inf_nan=False)


class AutoExport(ApiModel):
    """Render the best highlights automatically as soon as analysis finishes."""

    top: int = Field(5, ge=1, le=10)
    aspect: Aspect = "vertical_blur"
    title_overlay: bool = True
    captions: bool = False
    caption_style: CaptionStyle = "bold"
    caption_position: float = Field(0.72, ge=0.3, le=0.92)
    watermark: str | None = Field(None, max_length=40)
    replay: bool = False
    normalize: bool = True


class AnalyzeSettings(ApiModel):
    length: Literal["short", "medium", "long"] = "short"
    max_clips: int = Field(12, ge=1, le=30)
    sensitivity: float = Field(0.5, ge=0.0, le=1.0)
    use_ai: bool = True
    auto_export: AutoExport | None = None


class CaptionWord(ApiModel):
    start: float = Field(ge=0, le=MAX_CLIP_SECONDS)
    end: float = Field(ge=0, le=MAX_CLIP_SECONDS)
    text: str = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def _ordered(self) -> "CaptionWord":
        if self.end < self.start:
            raise ValueError("Caption word ends before it starts")
        return self


class TranscriptCreate(ApiModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)

    @model_validator(mode="after")
    def _check_range(self) -> "TranscriptCreate":
        if not (0.5 < self.end - self.start <= MAX_CLIP_SECONDS):
            raise ValueError(f"Pick a range between 0.5 and {MAX_CLIP_SECONDS} seconds")
        return self


class ClipCreate(ApiModel):
    highlight_id: str | None = None
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    aspect: Aspect = "vertical_blur"
    crop_x: float = Field(0.5, ge=0.0, le=1.0)
    title_overlay: bool = False
    title: str | None = Field(None, max_length=120)
    quality: Literal["high", "fast"] = "high"
    captions: bool = False
    caption_style: CaptionStyle = "bold"
    caption_position: float = Field(0.72, ge=0.3, le=0.92)
    watermark: str | None = Field(None, max_length=40)
    replay: bool = False
    normalize: bool = True
    # Captions the user reviewed/edited (times relative to the clip start).
    caption_words: list[CaptionWord] | None = Field(None, max_length=3000)

    @model_validator(mode="after")
    def _check_range(self) -> "ClipCreate":
        if self.end <= self.start + 0.5:
            raise ValueError("Clip end must be at least 0.5s after its start")
        if self.end - self.start > MAX_CLIP_SECONDS:
            raise ValueError(f"Clips can be at most {MAX_CLIP_SECONDS} seconds long")
        return self


class ExportAll(ApiModel):
    aspect: Aspect = "vertical_blur"
    title_overlay: bool = True
    top: int = Field(5, ge=1, le=30)
    replay: bool = False
    normalize: bool = True
    quality: Literal["high", "fast"] = "high"
    captions: bool = False
    caption_style: CaptionStyle = "bold"
    caption_position: float = Field(0.72, ge=0.3, le=0.92)
    watermark: str | None = Field(None, max_length=40)


class Rect(ApiModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(gt=0.02, le=1)
    h: float = Field(gt=0.02, le=1)

    @model_validator(mode="after")
    def _inside(self) -> "Rect":
        if self.x + self.w > 1.001 or self.y + self.h > 1.001:
            raise ValueError("Rectangle must be inside the frame")
        return self


class LayoutUpdate(ApiModel):
    facecam: Rect | None = None


class ImportRequest(AnalyzeSettings):
    url: str = Field(min_length=8, max_length=2000)


class UploadStart(AnalyzeSettings):
    filename: str = Field(min_length=1, max_length=255)
    size: int = Field(gt=0)
    fingerprint: str = Field(min_length=1, max_length=400)


class WorkspaceSwitch(ApiModel):
    key: str = Field(min_length=32, max_length=64)


class MontageCreate(ApiModel):
    highlight_ids: list[str] = Field(min_length=2, max_length=20)
    normalize: bool = True
    order: Literal["as_given", "timeline", "score"] = "as_given"
    transition: Literal["fade", "fadeblack", "slideleft", "cut"] = "fade"
    aspect: Aspect = "vertical_blur"
    title_overlay: bool = True
    captions: bool = False
    caption_style: CaptionStyle = "bold"
    caption_position: float = Field(0.72, ge=0.3, le=0.92)
    quality: Literal["high", "fast"] = "high"
    watermark: str | None = Field(None, max_length=40)


class VideoPatch(ApiModel):
    name: str = Field(min_length=1, max_length=200)


class HighlightCreate(ApiModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    title: str | None = Field(None, max_length=120)

    @model_validator(mode="after")
    def _check_range(self) -> "HighlightCreate":
        if self.end <= self.start + 1:
            raise ValueError("A highlight must be at least 1 second long")
        if self.end - self.start > MAX_CLIP_SECONDS:
            raise ValueError(f"Highlights can be at most {MAX_CLIP_SECONDS} seconds long")
        return self


class HighlightPatch(ApiModel):
    title: str | None = Field(None, max_length=120)
    caption: str | None = Field(None, max_length=600)
    start: float | None = Field(None, ge=0)
    end: float | None = Field(None, gt=0)
