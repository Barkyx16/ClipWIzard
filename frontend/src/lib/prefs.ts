import type { CaptionStyle, EditorState } from "../components/ClipEditor";

/** Small, failure-tolerant wrappers around localStorage (private mode can throw). */
export function loadPref(key: string, fallback: string): string {
  try {
    return localStorage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
}

export function savePref(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* storage unavailable (private mode) */
  }
}

const WATERMARK_KEY = "cw_watermark";
export const FORMAT_KEY = "cw_format";
export type Format = Omit<EditorState, "start" | "end" | "title">;

export const DEFAULT_FORMAT: Format = {
  aspect: "vertical_blur",
  cropX: 0.5,
  titleOverlay: true,
  captions: true,
  captionStyle: "bold" as CaptionStyle,
  captionPosition: 0.72,
  watermark: "",
  replay: false,
  normalize: true,
};

export function pickFormat(e: EditorState): Format {
  const { start: _s, end: _e, title: _t, ...format } = e;
  return format;
}

/** Saved format, keeping only known keys with the right types. */
export function loadFormat(): Partial<Format> {
  const out: Record<string, unknown> = {};
  try {
    const saved = JSON.parse(loadPref(FORMAT_KEY, "{}")) as Record<string, unknown>;
    // Older versions stored these two separately.
    saved.watermark ??= loadPref(WATERMARK_KEY, "");
    saved.captionStyle ??= loadPref("cw_caption_style", "bold");
    for (const [k, v] of Object.entries(DEFAULT_FORMAT)) {
      if (typeof saved[k] === typeof v) out[k] = saved[k];
    }
    const aspects = ["vertical_blur", "vertical_smart", "vertical_facecam", "vertical_crop", "square", "landscape"];
    if (!aspects.includes(out.aspect as string)) delete out.aspect;
    if (!["bold", "neon", "clean"].includes(out.captionStyle as string)) delete out.captionStyle;
  } catch {
    /* corrupt or missing: defaults */
  }
  return out as Partial<Format>;
}
