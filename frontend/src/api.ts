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
  exportAll: (videoId: string, body: { aspect: Aspect; title_overlay: boolean; top: number; captions: boolean }) =>
    request<Clip[]>(`/api/videos/${videoId}/export-all`, { method: "POST", body: JSON.stringify(body) }),
  deleteClip: (id: string) => request<void>(`/api/clips/${id}`, { method: "DELETE" }),
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

/** Streams the file as the raw request body so we get real upload progress. */
export const isBusy = (v: Pick<Video, "status">) =>
  v.status === "queued" || v.status === "analyzing" || v.status === "downloading";

export function uploadVideo(
  file: File,
  settings: AnalyzeSettings,
  onProgress: (loaded: number, total: number) => void,
): UploadHandle {
  const xhr = new XMLHttpRequest();
  const params = new URLSearchParams({
    filename: file.name,
    length: settings.length,
    max_clips: String(settings.max_clips),
    sensitivity: String(settings.sensitivity),
    use_ai: String(settings.use_ai),
  });
  const promise = new Promise<Video>((resolve, reject) => {
    xhr.open("POST", `/api/videos?${params}`);
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.upload.onprogress = (e) => onProgress(e.loaded, e.lengthComputable ? e.total : file.size);
    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* non-JSON error page */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as Video);
      else reject(new ApiError(xhr.status, errorMessage(body, `Upload failed (${xhr.status})`)));
    };
    xhr.onerror = () => reject(new ApiError(0, "Network error while uploading"));
    xhr.onabort = () => reject(new ApiError(0, "Upload cancelled"));
    xhr.send(file);
  });
  return { promise, abort: () => xhr.abort() };
}
