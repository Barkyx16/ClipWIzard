export type VideoStatus = "uploaded" | "downloading" | "queued" | "analyzing" | "ready" | "failed";
export type ClipStatus = "queued" | "rendering" | "done" | "failed";
export type Aspect = "vertical_blur" | "vertical_smart" | "vertical_facecam" | "vertical_crop" | "square" | "landscape";

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}
export type ClipLength = "short" | "medium" | "long";

export interface AnalyzeSettings {
  length: ClipLength;
  max_clips: number;
  sensitivity: number;
  use_ai: boolean;
}

export interface HighlightSignals {
  audio?: number;
  gunfire?: number;
  motion?: number;
  impact_db?: number;
  onset_rate?: number;
  excitement?: number;
  ai_hype?: number;
  is_gameplay?: boolean;
}

export interface Highlight {
  id: string;
  video_id: string;
  rank: number;
  start: number;
  end: number;
  peak: number;
  score: number;
  category: string;
  title: string;
  description: string | null;
  caption: string | null;
  hashtags: string[];
  signals: HighlightSignals;
  ai_enriched: boolean;
  thumbnail_url: string | null;
}

export interface ClipOptions {
  aspect: Aspect;
  crop_x: number;
  title_overlay: boolean;
  title: string | null;
  quality: "high" | "fast";
  captions: boolean;
  caption_style?: string;
  caption_position?: number;
  watermark?: string | null;
  replay?: boolean;
  normalize?: boolean;
  kind?: "montage";
  segments?: { highlight_id: string; start: number; end: number; title: string }[];
  transition?: string;
}

export interface Clip {
  id: string;
  video_id: string;
  highlight_id: string | null;
  start: number;
  end: number;
  options: ClipOptions;
  status: ClipStatus;
  progress: number;
  error: string | null;
  warning: string | null;
  transcript: string | null;
  size_bytes: number | null;
  created_at: number;
  url: string | null;
  download_url: string | null;
  share_url: string | null;
}

export interface SharedClip {
  title: string;
  caption: string | null;
  hashtags: string[];
  duration: number;
  aspect: Aspect | null;
  video_url: string;
  download_url: string;
}

export interface Video {
  id: string;
  name: string;
  size_bytes: number;
  duration: number;
  width: number;
  height: number;
  fps: number;
  has_audio: boolean;
  status: VideoStatus;
  stage: string | null;
  progress: number;
  error: string | null;
  settings: AnalyzeSettings;
  ai_used: boolean;
  layout: { facecam?: Rect };
  import_url: string | null;
  queue_ahead: number;
  created_at: number;
  source_url: string;
  thumbnail_url: string | null;
  highlights?: Highlight[];
  clips?: Clip[];
}

export interface Timeline {
  hop: number;
  excitement: number[];
  audio: number[];
  motion: number[];
  /** Smart-crop camera path (crop centre 0..1), one value per crop_hop seconds. */
  crop_path?: number[];
  crop_hop?: number;
}

export interface Health {
  ok: boolean;
  ai_enabled: boolean;
  model: string | null;
  max_upload_mb: number;
  allowed_extensions: string[];
  captions_available: boolean;
  import_sites: string[];
  retention_days?: number;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

function errorMessage(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg).replace(/^Value error, /, "");
  }
  return fallback;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: init?.body ? { "Content-Type": "application/json", ...init.headers } : init?.headers,
  });
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, errorMessage(body, `Request failed (${res.status})`));
  return body as T;
}

export const api = {
  health: () => request<Health>("/api/health"),
  videos: () => request<Video[]>("/api/videos"),
  video: (id: string) => request<Video>(`/api/videos/${id}`),
  renameVideo: (id: string, name: string) =>
    request<Video>(`/api/videos/${id}`, { method: "PATCH", body: JSON.stringify({ name }) }),
  importLink: (url: string, settings: AnalyzeSettings) =>
    request<Video>("/api/videos/import", { method: "POST", body: JSON.stringify({ url, ...settings }) }),
  timeline: (id: string) => request<Timeline>(`/api/videos/${id}/timeline`),
  deleteVideo: (id: string) => request<void>(`/api/videos/${id}`, { method: "DELETE" }),
  reanalyze: (id: string, settings: AnalyzeSettings) =>
    request<Video>(`/api/videos/${id}/reanalyze`, { method: "POST", body: JSON.stringify(settings) }),
  patchHighlight: (id: string, patch: Partial<Pick<Highlight, "title" | "caption" | "start" | "end">>) =>
    request<Highlight>(`/api/highlights/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  createClip: (
    videoId: string,
    body: { highlight_id?: string | null; start: number; end: number } & Partial<ClipOptions>,
  ) => request<Clip>(`/api/videos/${videoId}/clips`, { method: "POST", body: JSON.stringify(body) }),
  exportAll: (
    videoId: string,
    body: {
      aspect: Aspect;
      title_overlay: boolean;
      top: number;
      captions: boolean;
      watermark?: string | null;
      caption_style?: string;
      caption_position?: number;
      replay?: boolean;
      normalize?: boolean;
    },
  ) => request<Clip[]>(`/api/videos/${videoId}/export-all`, { method: "POST", body: JSON.stringify(body) }),
  createHighlight: (videoId: string, body: { start: number; end: number; title?: string }) =>
    request<Highlight>(`/api/videos/${videoId}/highlights`, { method: "POST", body: JSON.stringify(body) }),
  deleteHighlight: (id: string) => request<void>(`/api/highlights/${id}`, { method: "DELETE" }),
  createMontage: (
    videoId: string,
    body: {
      highlight_ids: string[];
      order: "as_given" | "timeline" | "score";
      transition: "fade" | "fadeblack" | "slideleft" | "cut";
      aspect: Aspect;
      title_overlay: boolean;
      captions: boolean;
      watermark?: string | null;
      caption_style?: string;
      caption_position?: number;
      normalize?: boolean;
    },
  ) => request<Clip>(`/api/videos/${videoId}/montage`, { method: "POST", body: JSON.stringify(body) }),
  deleteClip: (id: string) => request<void>(`/api/clips/${id}`, { method: "DELETE" }),
  shareClip: (id: string) => request<Clip>(`/api/clips/${id}/share`, { method: "POST" }),
  unshareClip: (id: string) => request<Clip>(`/api/clips/${id}/share`, { method: "DELETE" }),
  shared: (token: string) => request<SharedClip>(`/api/share/${token}`),
  updateLayout: (videoId: string, layout: { facecam: Rect | null }) =>
    request<{ facecam?: Rect }>(`/api/videos/${videoId}/layout`, { method: "PUT", body: JSON.stringify(layout) }),
  workspace: () => request<{ key: string }>("/api/workspace"),
  switchWorkspace: (key: string) =>
    request<{ ok: boolean; videos: number }>("/api/workspace", { method: "POST", body: JSON.stringify({ key }) }),
};

export interface UploadHandle {
  promise: Promise<Video>;
  abort: () => void;
}

interface UploadSession {
  id: string;
  filename: string;
  size: number;
  received: number;
  chunk_size: number;
}

export interface UploadCallbacks {
  onProgress: (loaded: number, total: number) => void;
  /** Human-readable status changes: resuming, retrying after a dropped connection... */
  onStatus?: (message: string | null) => void;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

function putChunk(
  uploadId: string,
  offset: number,
  blob: Blob,
  onLoaded: (loaded: number) => void,
  track: (xhr: XMLHttpRequest | null) => void,
): Promise<UploadSession> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    track(xhr);
    xhr.open("PUT", `/api/uploads/${uploadId}?offset=${offset}`);
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.upload.onprogress = (e) => onLoaded(e.loaded);
    xhr.onload = () => {
      track(null);
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* ignore */
      }
      if (xhr.status >= 200 && xhr.status < 300) return resolve(body as UploadSession);
      const err = new ApiError(xhr.status, errorMessage(body, `Upload failed (${xhr.status})`));
      const detail = (body as { detail?: { received?: number } } | null)?.detail;
      if (detail && typeof detail === "object" && typeof detail.received === "number") {
        (err as ApiError & { received?: number }).received = detail.received;
      }
      reject(err);
    };
    xhr.onerror = () => {
      track(null);
      reject(new ApiError(0, "Network error while uploading"));
    };
    xhr.onabort = () => {
      track(null);
      reject(new ApiError(-1, "Upload cancelled"));
    };
    xhr.send(blob);
  });
}

/**
 * Uploads in chunks so huge recordings survive flaky connections: failed
 * chunks are retried with backoff, and picking the same file again resumes
 * where the last attempt stopped.
 */
export function uploadVideo(file: File, settings: AnalyzeSettings, cb: UploadCallbacks): UploadHandle {
  let cancelled = false;
  let current: XMLHttpRequest | null = null;
  let uploadId: string | null = null;
  const fingerprint = `${file.name}:${file.size}:${file.lastModified}`;

  const promise = (async () => {
    const session = await request<UploadSession>("/api/uploads", {
      method: "POST",
      body: JSON.stringify({ filename: file.name, size: file.size, fingerprint, ...settings }),
    });
    uploadId = session.id;
    let offset = session.received;
    if (offset > 0) cb.onStatus?.(`Resuming from ${Math.round((offset / file.size) * 100)}%`);
    cb.onProgress(offset, file.size);

    while (offset < file.size) {
      const end = Math.min(file.size, offset + session.chunk_size);
      for (let attempt = 0; ; attempt++) {
        if (cancelled) throw new ApiError(-1, "Upload cancelled");
        try {
          const res = await putChunk(
            session.id,
            offset,
            file.slice(offset, end),
            (loaded) => cb.onProgress(offset + loaded, file.size),
            (x) => (current = x),
          );
          offset = res.received;
          if (attempt > 0) cb.onStatus?.(null);
          break;
        } catch (e) {
          if (cancelled || !(e instanceof ApiError)) throw e;
          const received = (e as ApiError & { received?: number }).received;
          if (e.status === 409 && typeof received === "number") {
            offset = received; // server knows better where we are
            break;
          }
          const retryable = e.status === 0 || e.status === 408 || e.status === 429 || e.status >= 500;
          if (!retryable || attempt >= 8) throw e;
          const wait = Math.min(30_000, 1000 * 2 ** attempt);
          cb.onStatus?.(`Connection hiccup. Retrying in ${Math.round(wait / 1000)}s…`);
          await sleep(wait);
        }
      }
      cb.onProgress(offset, file.size);
    }
    cb.onStatus?.(null);
    return request<Video>(`/api/uploads/${session.id}/complete`, { method: "POST" });
  })();

  return {
    promise,
    abort: () => {
      cancelled = true;
      current?.abort();
      if (uploadId) fetch(`/api/uploads/${uploadId}`, { method: "DELETE" }).catch(() => undefined);
    },
  };
}

export const isBusy = (v: Pick<Video, "status">) =>
  v.status === "queued" || v.status === "analyzing" || v.status === "downloading";
