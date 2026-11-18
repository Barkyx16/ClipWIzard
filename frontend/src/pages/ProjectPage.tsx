import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { AlertTriangle, ArrowLeft, Bot, Layers, Loader2, Play, RefreshCw, Repeat } from "lucide-react";

import { api, AnalyzeSettings, Clip, Health, Highlight, Rect, Timeline as TimelineData, Video } from "../api";
import ClipEditor, { EditorState } from "../components/ClipEditor";
import ExportCard from "../components/ExportCard";
import PlayerStage from "../components/PlayerStage";
import HighlightCard from "../components/HighlightCard";
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

function AnalyzingState({ video }: { video: Video }) {
  const [tip, setTip] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setTip((i) => (i + 1) % TIPS.length), 5000);
    return () => clearInterval(t);
  }, []);
  return (
    <div className="card mx-auto max-w-2xl p-8 text-center">
      <Loader2 className="mx-auto mb-4 h-10 w-10 animate-spin text-primary" />
      <h2 className="font-display text-4xl tracking-wide">{video.stage ?? "Queued"}…</h2>
      <p className="mt-2 text-sm text-muted">
        {formatTime(video.duration)} of footage. Long sessions take a few minutes; you can leave this page and come back.
      </p>
      <ProgressBar value={video.progress} className="mt-6 h-3" />
      <p className="mt-2 text-sm font-semibold">{Math.round(video.progress * 100)}%</p>
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
  const [editor, setEditor] = useState<EditorState>({
    start: 0,
    end: 15,
    aspect: "vertical_blur",
    cropX: 0.5,
    titleOverlay: true,
    title: "",
    captions: true,
  });
  const [health, setHealth] = useState<Health | null>(null);
  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
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

  const busy = video?.status === "queued" || video?.status === "analyzing";
  const rendering = clips.some((c) => c.status === "queued" || c.status === "rendering");
  usePolling(load, 1500, Boolean(busy || rendering));

  // Load the timeline and select the top highlight once analysis is done.
  useEffect(() => {
    if (video?.status !== "ready") return;
    api.timeline(video.id).then(setTimeline).catch(() => setTimeline(null));
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
      });
      load();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Export failed");
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
    highlights.find((h) => h.id === c.highlight_id)?.title ?? c.options.title ?? "Custom clip";

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
          <h1 className="truncate font-display text-4xl tracking-wide sm:text-5xl" title={video.name}>
            {video.name}
          </h1>
          <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted">
            <span>{formatTime(video.duration)}</span>
            <span>
              {video.width}×{video.height} @ {Math.round(video.fps)}fps
            </span>
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
            <p className="font-semibold text-bad">Analysis failed</p>
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
            <section className="card p-4" aria-labelledby="highlights-heading">
              <div className="mb-3 flex items-center justify-between">
                <h2 id="highlights-heading" className="font-display text-2xl tracking-wide">
                  Highlights
                </h2>
                {highlights.length > 0 && (
                  <button type="button" className="btn-ghost px-3 py-1.5 text-xs" onClick={exportTop}>
                    <Layers className="h-4 w-4" /> Export top {Math.min(5, highlights.length)}
                  </button>
                )}
              </div>
              {highlights.length === 0 ? (
                <p className="py-6 text-center text-sm text-muted">
                  No big moments found. Try a re-scan with higher sensitivity, or trim a custom clip below.
                </p>
              ) : (
                <div className="max-h-[420px] space-y-2 overflow-y-auto pr-1">
                  {highlights.map((h) => (
                    <HighlightCard key={h.id} h={h} selected={h.id === selectedId} onSelect={(x) => select(x)} />
                  ))}
                </div>
              )}
            </section>

            <ClipEditor
              highlight={selected}
              state={editor}
              duration={video.duration}
              currentTime={currentTime}
              exporting={exporting}
              captionsAvailable={Boolean(health?.captions_available)}
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
            />
          </div>

          <section aria-labelledby="exports-heading" className="min-w-0 lg:col-start-1">
              <h2 id="exports-heading" className="mb-3 font-display text-3xl tracking-wide">
                Exports
              </h2>
              {clips.length === 0 ? (
                <p className="card px-4 py-8 text-center text-sm text-muted">
                  Exported clips show up here, ready to download.
                </p>
              ) : (
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4">
                  {clips.map((c) => (
                    <ExportCard key={c.id} clip={c} title={clipTitle(c)} onDelete={deleteClip} />
                  ))}
                </div>
              )}
          </section>
        </div>
      )}
    </div>
  );
}
