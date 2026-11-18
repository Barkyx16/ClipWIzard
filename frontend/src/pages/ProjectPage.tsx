import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { AlertTriangle, ArrowLeft, Bot, FolderDown, Loader2, Play, RefreshCw, Repeat } from "lucide-react";

import { api, AnalyzeSettings, Clip, Health, Highlight, isBusy, Rect, Timeline as TimelineData, Video } from "../api";
import CaptionReview, { CaptionReviewState } from "../components/CaptionReview";
import ClipEditor, { CaptionStyle, EditorState } from "../components/ClipEditor";
import { groupPhrases, phrasesToWords } from "../lib/captions";
import EditableTitle from "../components/EditableTitle";
import ExportCard from "../components/ExportCard";
import PlayerStage from "../components/PlayerStage";
import HighlightsPanel, { MontageOrder, Transition } from "../components/HighlightsPanel";
import ProgressBar from "../components/ProgressBar";
import Timeline from "../components/Timeline";
import { formatTime } from "../lib/format";
import { usePolling } from "../lib/usePolling";

const TIPS = [
  "Tip: vertical blur-fill keeps the whole frame visible, perfect for driving clips.",
  "Tip: use the crosshair buttons to set the clip start/end from the playhead.",
  "Tip: lower the sensitivity to keep only the biggest moments.",
  "Tip: burn the title in. Clips with on-screen hooks tend to hold viewers longer.",
];

const WATERMARK_KEY = "cw_watermark";

function loadPref(key: string, fallback: string): string {
  try {
    return localStorage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
}

function savePref(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* storage unavailable (private mode) */
  }
}

const FORMAT_KEY = "cw_format";
type Format = Omit<EditorState, "start" | "end" | "title">;
const DEFAULT_FORMAT: Format = {
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

function pickFormat(e: EditorState): Format {
  const { start: _s, end: _e, title: _t, ...format } = e;
  return format;
}

/** Saved format, keeping only known keys with the right types. */
function loadFormat(): Partial<Format> {
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

function Kbd({ children }: { children: string }) {
  return (
    <kbd className="mx-0.5 rounded border border-line bg-surface-2 px-1 py-px font-sans text-[10px] text-muted">
      {children}
    </kbd>
  );
}

/** Rough time left, from how fast progress has moved since this step started. */
function useEta(status: string, progress: number): number | null {
  const start = useRef<{ status: string; t: number; p: number } | null>(null);
  if (!start.current || start.current.status !== status || progress < start.current.p) {
    start.current = { status, t: Date.now(), p: progress };
  }
  const elapsed = (Date.now() - start.current.t) / 1000;
  const done = progress - start.current.p;
  if (elapsed < 5 || done < 0.03 || progress >= 1) return null;
  return (elapsed / done) * (1 - progress);
}

function formatEta(seconds: number): string {
  if (seconds < 60) return "less than a minute left";
  const m = Math.round(seconds / 60);
  return m < 60 ? `about ${m} min left` : `about ${Math.floor(m / 60)} h ${m % 60} min left`;
}

function AnalyzingState({ video }: { video: Video }) {
  const [tip, setTip] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setTip((i) => (i + 1) % TIPS.length), 5000);
    return () => clearInterval(t);
  }, []);
  const eta = useEta(video.status, video.progress);
  return (
    <div className="card mx-auto max-w-2xl p-8 text-center">
      <Loader2 className="mx-auto mb-4 h-10 w-10 animate-spin text-primary" />
      <h2 className="font-display text-4xl tracking-wide">
        {video.status === "queued" && video.queue_ahead > 0
          ? `${video.queue_ahead} ${video.queue_ahead === 1 ? "video" : "videos"} ahead of yours`
          : `${video.stage ?? "Queued"}…`}
      </h2>
      <p className="mt-2 text-sm text-muted">
        {video.status === "downloading"
          ? "Grabbing the video. Long VODs can take a while; you can leave this page and come back."
          : `${formatTime(video.duration)} of footage. Long sessions take a few minutes; you can leave this page and come back.`}
      </p>
      <ProgressBar value={video.progress} className="mt-6 h-3" />
      <p className="mt-2 text-sm font-semibold">
        {Math.round(video.progress * 100)}%
        {eta !== null && <span className="font-normal text-muted"> · {formatEta(eta)}</span>}
      </p>
      <p className="mt-6 text-xs text-dim">{TIPS[tip]}</p>
    </div>
  );
}

function RescanPanel({ video, onDone }: { video: Video; onDone: (v: Video) => void }) {
  const [settings, setSettings] = useState<AnalyzeSettings>(video.settings);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      onDone(await api.reanalyze(video.id, settings));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Re-scan failed");
    } finally {
      setBusy(false);
    }
  };
  return (
    <details className="relative">
      <summary className="btn-ghost cursor-pointer list-none">
        <RefreshCw className="h-4 w-4" /> Re-scan
      </summary>
      <div className="card absolute left-0 z-20 mt-2 w-72 space-y-3 p-4 shadow-2xl sm:left-auto sm:right-0">
        <label className="block">
          <span className="label">Clip length</span>
          <select
            className="input mt-1"
            value={settings.length}
            onChange={(e) => setSettings((s) => ({ ...s, length: e.target.value as AnalyzeSettings["length"] }))}
          >
            <option value="short">Short (12–30s)</option>
            <option value="medium">Medium (25–60s)</option>
            <option value="long">Long (45–90s)</option>
          </select>
        </label>
        <label className="block">
          <span className="label flex justify-between">
            Max clips <span className="text-ink">{settings.max_clips}</span>
          </span>
          <input
            type="range"
            min={1}
            max={30}
            value={settings.max_clips}
            onChange={(e) => setSettings((s) => ({ ...s, max_clips: Number(e.target.value) }))}
            className="mt-2 w-full"
          />
        </label>
        <label className="block">
          <span className="label">Sensitivity</span>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={settings.sensitivity}
            onChange={(e) => setSettings((s) => ({ ...s, sensitivity: Number(e.target.value) }))}
            className="mt-2 w-full"
          />
        </label>
        {error && <p className="text-xs text-bad">{error}</p>}
        <button type="button" className="btn-primary w-full" disabled={busy} onClick={run}>
          {busy && <Loader2 className="h-4 w-4 animate-spin" />} Scan again
        </button>
        <p className="text-[11px] text-dim">Exported clips are kept. Highlight edits will be replaced.</p>
      </div>
    </details>
  );
}

export default function ProjectPage() {
  const { id = "" } = useParams();
  const videoRef = useRef<HTMLVideoElement>(null);
  const [video, setVideo] = useState<Video | null>(null);
  const [timeline, setTimeline] = useState<TimelineData | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [loop, setLoop] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [drawingFacecam, setDrawingFacecam] = useState(false);
  const [captionReview, setCaptionReview] = useState<CaptionReviewState | null>(null);
  const [editor, setEditor] = useState<EditorState>(() => ({
    start: 0,
    end: 15,
    title: "",
    ...DEFAULT_FORMAT,
    ...loadFormat(),
  }));
  // Remember format choices (not the range or title) for the next session.
  const format = pickFormat(editor);
  const formatKey = JSON.stringify(format);
  useEffect(() => savePref(FORMAT_KEY, formatKey), [formatKey]);
  const [health, setHealth] = useState<Health | null>(null);
  useEffect(() => {
    api
      .health()
      .then(setHealth)
      .catch(() => setHealth(null));
  }, []);
  const captionsOn = editor.captions && Boolean(health?.captions_available);

  const highlights = useMemo(() => video?.highlights ?? [], [video]);
  const clips = useMemo(() => video?.clips ?? [], [video]);
  const selected = highlights.find((h) => h.id === selectedId) ?? null;

  const load = useCallback(async () => {
    try {
      const v = await api.video(id);
      setVideo(v);
    } catch (e) {
      if (e instanceof Error && "status" in e && (e as { status: number }).status === 404) setNotFound(true);
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  const busy = video ? isBusy(video) : false;
  const rendering = clips.some((c) => c.status === "queued" || c.status === "rendering");
  usePolling(load, 1500, Boolean(busy || rendering));

  // Tab title shows progress, so people can wait in another tab.
  const wasBusy = useRef(false);
  useEffect(() => {
    if (!video) return;
    if (isBusy(video)) {
      wasBusy.current = true;
      document.title = `${Math.round(video.progress * 100)}% · ${video.name} · ClipWizard`;
    } else if (video.status === "ready" && wasBusy.current) {
      document.title = `✅ Highlights ready · ${video.name} · ClipWizard`;
    } else {
      document.title = `${video.name} · ClipWizard`;
    }
  }, [video]);
  useEffect(() => () => void (document.title = "ClipWizard"), []);

  // Load the timeline and select the top highlight once analysis is done.
  useEffect(() => {
    if (video?.status !== "ready") return;
    api
      .timeline(video.id)
      .then(setTimeline)
      .catch(() => setTimeline(null));
  }, [video?.status, video?.id]);

  const select = useCallback((h: Highlight, play = true) => {
    setSelectedId(h.id);
    setEditor((s) => ({ ...s, start: h.start, end: h.end, title: h.title }));
    const el = videoRef.current;
    if (el) {
      el.currentTime = h.start;
      if (play) el.play().catch(() => undefined);
    }
  }, []);

  useEffect(() => {
    if (video?.status === "ready" && highlights.length && !highlights.some((h) => h.id === selectedId)) {
      select(highlights[0], false);
    }
  }, [video?.status, highlights, selectedId, select]);

  // Keep the edit range inside the video (e.g. short videos with no highlights).
  const duration = video?.duration ?? 0;
  useEffect(() => {
    if (!duration) return;
    setEditor((s) =>
      s.end > duration || s.start >= duration
        ? { ...s, start: Math.min(s.start, Math.max(0, duration - 1)), end: duration }
        : s,
    );
  }, [duration]);

  const onTimeUpdate = () => {
    const el = videoRef.current;
    if (!el) return;
    if (loop && editor.end > editor.start && el.currentTime >= editor.end) {
      el.currentTime = editor.start;
    }
    setCurrentTime(el.currentTime);
  };

  // Keyboard shortcuts (ignored while typing in a field).
  const shortcuts = useRef<(e: KeyboardEvent) => void>(() => undefined);
  shortcuts.current = (e: KeyboardEvent) => {
    const el = videoRef.current;
    const target = e.target as HTMLElement | null;
    if (!el || !video || drawingFacecam || e.metaKey || e.ctrlKey || e.altKey) return;
    if (target?.closest("input, textarea, select, [contenteditable=true]")) return;
    // Let focused native controls keep their own keys.
    if (target?.tagName === "VIDEO" && [" ", "ArrowLeft", "ArrowRight"].includes(e.key)) return;
    if (e.key === " " && target?.closest("button, a, summary, [role=slider], [role=checkbox], [role=tab]")) return;
    const t = el.currentTime;
    const idx = highlights.findIndex((h) => h.id === selectedId);
    const handled = (() => {
      switch (e.key) {
        case " ":
        case "k":
          if (el.paused) el.play().catch(() => undefined);
          else el.pause();
          return true;
        case "i":
          setEditor((s) => ({ ...s, start: Math.min(t, s.end - 1) }));
          return true;
        case "o":
          setEditor((s) => ({ ...s, end: Math.max(t, s.start + 1) }));
          return true;
        case "ArrowLeft":
          seek(Math.max(0, t - (e.shiftKey ? 1 : 5)));
          return true;
        case "ArrowRight":
          seek(Math.min(video.duration, t + (e.shiftKey ? 1 : 5)));
          return true;
        case "j":
          seek(Math.max(0, t - 10));
          return true;
        case "l":
          seek(Math.min(video.duration, t + 10));
          return true;
        case "[":
          if (idx > 0) select(highlights[idx - 1]);
          return true;
        case "]":
          if (idx < highlights.length - 1) select(highlights[idx + 1]);
          return true;
        default:
          return false;
      }
    })();
    if (handled) e.preventDefault();
  };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => shortcuts.current(e);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const seek = (t: number) => {
    const el = videoRef.current;
    if (el) el.currentTime = t;
    setCurrentTime(t);
  };

  const playRange = () => {
    const el = videoRef.current;
    if (!el) return;
    el.currentTime = editor.start;
    el.play().catch(() => undefined);
  };

  const exportClip = async () => {
    if (!video) return;
    setExporting(true);
    setActionError(null);
    try {
      if (selected && editor.title && editor.title !== selected.title) {
        await api.patchHighlight(selected.id, { title: editor.title });
      }
      const clip = await api.createClip(video.id, {
        highlight_id: selected?.id ?? null,
        start: editor.start,
        end: editor.end,
        aspect: editor.aspect,
        crop_x: editor.cropX,
        title_overlay: editor.titleOverlay && editor.title.trim() !== "",
        title: editor.title.trim() || null,
        captions: captionsOn,
        caption_words: captionsOn ? reviewedWords : undefined,
        watermark: editor.watermark.trim() || null,
        caption_style: editor.captionStyle,
        caption_position: editor.captionPosition,
        normalize: editor.normalize,
        replay: editor.replay,
      });
      setVideo((v) => (v ? { ...v, clips: [clip, ...(v.clips ?? [])] } : v));
      load();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Export failed");
    } finally {
      setExporting(false);
    }
  };

  const exportTop = async () => {
    if (!video) return;
    setActionError(null);
    try {
      await api.exportAll(video.id, {
        aspect:
          editor.aspect === "vertical_crop" || (editor.aspect === "vertical_facecam" && !video.layout?.facecam)
            ? "vertical_blur"
            : editor.aspect,
        title_overlay: editor.titleOverlay,
        top: Math.min(5, highlights.length),
        captions: captionsOn,
        watermark: editor.watermark.trim() || null,
        caption_style: editor.captionStyle,
        caption_position: editor.captionPosition,
        normalize: editor.normalize,
        replay: editor.replay,
      });
      load();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Export failed");
    }
  };

  const makeMontage = async (ids: string[], order: MontageOrder, transition: Transition) => {
    if (!video) return false;
    setActionError(null);
    try {
      const clip = await api.createMontage(video.id, {
        highlight_ids: ids,
        order,
        transition,
        aspect: editor.aspect === "vertical_crop" ? "vertical_smart" : editor.aspect,
        title_overlay: editor.titleOverlay,
        captions: captionsOn,
        watermark: editor.watermark.trim() || null,
        caption_style: editor.captionStyle,
        caption_position: editor.captionPosition,
        normalize: editor.normalize,
      });
      setVideo((v) => (v ? { ...v, clips: [clip, ...(v.clips ?? [])] } : v));
      document.getElementById("exports-heading")?.scrollIntoView({ behavior: "smooth", block: "start" });
      load();
      return true;
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Montage failed");
      return false;
    }
  };

  const reviewStale =
    captionReview !== null &&
    (Math.abs(captionReview.start - editor.start) > 0.05 || Math.abs(captionReview.end - editor.end) > 0.05);

  const startCaptionReview = async () => {
    if (!video) return;
    const range = { start: editor.start, end: editor.end };
    setCaptionReview({ ...range, status: "running", error: null, phrases: [] });
    try {
      let t = await api.createTranscript(video.id, range);
      while (t.status === "queued" || t.status === "running") {
        await new Promise((r) => setTimeout(r, 1000));
        t = await api.transcript(t.id);
      }
      setCaptionReview((cur) =>
        cur && cur.start === range.start && cur.end === range.end
          ? {
              ...range,
              status: t.status === "done" ? "done" : "failed",
              error: t.error,
              phrases: groupPhrases(t.words),
            }
          : cur,
      );
    } catch (e) {
      setCaptionReview({ ...range, status: "failed", error: e instanceof Error ? e.message : "Failed", phrases: [] });
    }
  };

  const reviewedWords =
    captionReview && !reviewStale && captionReview.status === "done" && captionReview.phrases.length
      ? phrasesToWords(captionReview.phrases)
      : undefined;

  const saveHighlight = async () => {
    if (!video) return;
    setActionError(null);
    try {
      const h = await api.createHighlight(video.id, {
        start: editor.start,
        end: editor.end,
        title: editor.title.trim() || undefined,
      });
      const fresh = await api.video(video.id);
      setVideo(fresh);
      setSelectedId(h.id);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Could not save the highlight");
    }
  };

  const deleteHighlight = async () => {
    if (!video || !selected) return;
    if (!confirm(`Remove "${selected.title}" from the highlights?`)) return;
    setActionError(null);
    try {
      await api.deleteHighlight(selected.id);
      setSelectedId(null);
      setVideo(await api.video(video.id));
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Could not remove the highlight");
    }
  };

  const saveFacecam = async (rect: Rect | null) => {
    if (!video) return;
    setDrawingFacecam(false);
    setActionError(null);
    try {
      const layout = await api.updateLayout(video.id, { facecam: rect });
      setVideo((v) => (v ? { ...v, layout } : v));
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Could not save the facecam area");
    }
  };

  const deleteClip = async (c: Clip) => {
    try {
      await api.deleteClip(c.id);
      setVideo((v) => (v ? { ...v, clips: (v.clips ?? []).filter((x) => x.id !== c.id) } : v));
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Delete failed");
    }
  };

  const clipTitle = (c: Clip) =>
    c.options.kind === "montage"
      ? `Montage: ${c.options.segments?.length ?? 0} moments`
      : (highlights.find((h) => h.id === c.highlight_id)?.title ?? c.options.title ?? "Custom clip");

  if (notFound) {
    return (
      <div className="card mx-auto max-w-lg p-8 text-center">
        <p className="text-lg font-semibold">That session doesn't exist.</p>
        <Link to="/" className="btn-ghost mt-4">
          <ArrowLeft className="h-4 w-4" /> Back to sessions
        </Link>
      </div>
    );
  }
  if (!video) {
    return (
      <div className="flex justify-center py-24">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="min-w-0">
          <Link to="/" className="mb-1 inline-flex items-center gap-1 text-sm text-muted hover:text-ink">
            <ArrowLeft className="h-4 w-4" /> Sessions
          </Link>
          <EditableTitle
            value={video.name}
            onSave={async (name) => {
              try {
                setVideo(await api.renameVideo(video.id, name));
              } catch (e) {
                setActionError(e instanceof Error ? e.message : "Rename failed");
              }
            }}
          />
          <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted">
            {video.duration ? <span>{formatTime(video.duration)}</span> : null}
            {video.width ? (
              <span>
                {video.width}×{video.height} @ {Math.round(video.fps)}fps
              </span>
            ) : null}
            {video.import_url && (
              <a
                href={video.import_url}
                target="_blank"
                rel="noreferrer noopener"
                className="underline-offset-2 hover:text-ink hover:underline"
              >
                Source link
              </a>
            )}
            {video.status === "ready" && <span>{highlights.length} highlights</span>}
            {video.ai_used && (
              <span className="inline-flex items-center gap-1 text-accent">
                <Bot className="h-4 w-4" /> AI enriched
              </span>
            )}
          </p>
        </div>
        {!busy && <RescanPanel video={video} onDone={setVideo} />}
      </div>

      {busy && <AnalyzingState video={video} />}

      {video.status === "failed" && (
        <div className="card flex items-start gap-3 border-bad/40 p-5 text-sm">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-bad" />
          <div>
            <p className="font-semibold text-bad">
              {video.stage === "Import failed" ? "Import failed" : "Analysis failed"}
            </p>
            <p className="mt-1 break-words text-muted">{video.error}</p>
          </div>
        </div>
      )}

      {actionError && (
        <p className="rounded-lg border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad" role="alert">
          {actionError}
        </p>
      )}

      {video.status === "ready" && (
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_400px] lg:grid-rows-[auto_1fr] lg:items-start">
          <div className="min-w-0 space-y-4">
            <div className="card overflow-hidden p-2">
              <PlayerStage
                ref={videoRef}
                video={video}
                aspect={editor.aspect}
                cropX={editor.cropX}
                currentTime={currentTime}
                timeline={timeline}
                drawing={drawingFacecam}
                onTimeUpdate={onTimeUpdate}
                onFacecamDrawn={saveFacecam}
                onCancelDrawing={() => setDrawingFacecam(false)}
              />
              <div className="flex flex-wrap items-center gap-2 px-2 pb-1 pt-3">
                <button type="button" className="btn-ghost py-2" onClick={playRange}>
                  <Play className="h-4 w-4" /> Play clip
                </button>
                <button
                  type="button"
                  className={`btn-ghost py-2 ${loop ? "border-accent text-accent" : ""}`}
                  aria-pressed={loop}
                  onClick={() => setLoop((l) => !l)}
                >
                  <Repeat className="h-4 w-4" /> Loop
                </button>
                <span className="ml-auto font-mono text-sm text-muted">
                  {formatTime(currentTime, true)} / {formatTime(video.duration)}
                </span>
                <p className="hidden w-full text-[11px] text-dim md:block">
                  <Kbd>Space</Kbd> play · <Kbd>I</Kbd>/<Kbd>O</Kbd> set start/end · <Kbd>←</Kbd>
                  <Kbd>→</Kbd> 5s (<Kbd>Shift</Kbd> 1s) · <Kbd>J</Kbd>/<Kbd>L</Kbd> 10s · <Kbd>[</Kbd>
                  <Kbd>]</Kbd> prev/next highlight
                </p>
              </div>
            </div>

            <Timeline
              data={timeline}
              duration={video.duration}
              highlights={highlights}
              selectedId={selectedId}
              currentTime={currentTime}
              range={{ start: editor.start, end: editor.end }}
              onSeek={seek}
              onSelect={(h) => select(h)}
            />
          </div>

          <div className="space-y-4 lg:col-start-2 lg:row-span-2 lg:row-start-1">
            <HighlightsPanel
              highlights={highlights}
              selectedId={selectedId}
              onSelect={(h) => select(h)}
              onExportTop={exportTop}
              onMontage={makeMontage}
            />

            <ClipEditor
              highlight={selected}
              state={editor}
              duration={video.duration}
              currentTime={currentTime}
              exporting={exporting}
              captionsAvailable={Boolean(health?.captions_available)}
              captionReview={
                <CaptionReview
                  review={captionReview}
                  stale={reviewStale}
                  onStart={startCaptionReview}
                  onEdit={(i, text) =>
                    setCaptionReview((r) =>
                      r ? { ...r, phrases: r.phrases.map((p, j) => (j === i ? { ...p, text } : p)) } : r,
                    )
                  }
                  onReset={() =>
                    setCaptionReview((r) =>
                      r ? { ...r, phrases: r.phrases.map((p) => ({ ...p, text: p.original })) } : r,
                    )
                  }
                />
              }
              hasFacecam={Boolean(video.layout?.facecam)}
              drawingFacecam={drawingFacecam}
              onMarkFacecam={() => {
                setDrawingFacecam((d) => !d);
                videoRef.current?.pause();
                videoRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
              }}
              onClearFacecam={() => saveFacecam(null)}
              onChange={(patch) => setEditor((s) => ({ ...s, ...patch }))}
              onExport={exportClip}
              onSaveHighlight={saveHighlight}
              onDeleteHighlight={deleteHighlight}
            />
          </div>

          <section aria-labelledby="exports-heading" className="min-w-0 lg:col-start-1">
            <div className="mb-3 flex items-center justify-between gap-3">
              <h2 id="exports-heading" className="font-display text-3xl tracking-wide">
                Exports
              </h2>
              {clips.filter((c) => c.status === "done").length > 1 && (
                <a href={`/api/videos/${video.id}/clips.zip`} className="btn-ghost px-3 py-1.5 text-xs" download>
                  <FolderDown className="h-4 w-4" /> Download all
                </a>
              )}
            </div>
            {clips.length === 0 ? (
              <p className="card px-4 py-8 text-center text-sm text-muted">
                Exported clips show up here, ready to download.
              </p>
            ) : (
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4">
                {clips.map((c) => (
                  <ExportCard
                    key={c.id}
                    clip={c}
                    title={clipTitle(c)}
                    onDelete={deleteClip}
                    onChange={(updated) =>
                      setVideo((v) =>
                        v ? { ...v, clips: (v.clips ?? []).map((x) => (x.id === updated.id ? updated : x)) } : v,
                      )
                    }
                  />
                ))}
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
