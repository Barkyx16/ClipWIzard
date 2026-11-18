import { useCallback, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Bot, FileVideo, Loader2, UploadCloud, X } from "lucide-react";

import { AnalyzeSettings, ClipLength, Health, UploadHandle, uploadVideo } from "../api";
import { formatBytes } from "../lib/format";
import ProgressBar from "./ProgressBar";

const LENGTHS: { value: ClipLength; label: string; hint: string }[] = [
  { value: "short", label: "Short", hint: "12–30s" },
  { value: "medium", label: "Medium", hint: "25–60s" },
  { value: "long", label: "Long", hint: "45–90s" },
];

export default function UploadCard({ health }: { health: Health | null }) {
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const handleRef = useRef<UploadHandle | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<{ loaded: number; total: number; started: number } | null>(null);
  const [settings, setSettings] = useState<AnalyzeSettings>({
    length: "short",
    max_clips: 12,
    sensitivity: 0.5,
    use_ai: true,
  });

  const aiAvailable = health?.ai_enabled ?? false;
  const accept = (health?.allowed_extensions ?? [".mp4", ".mov", ".mkv", ".webm"]).join(",");

  const pick = useCallback(
    (f: File | undefined) => {
      if (!f) return;
      setError(null);
      const ext = "." + (f.name.split(".").pop() ?? "").toLowerCase();
      if (health && !health.allowed_extensions.includes(ext)) {
        setError(`That file type isn't supported. Try ${health.allowed_extensions.join(", ")}.`);
        return;
      }
      if (health && f.size > health.max_upload_mb * 1024 * 1024) {
        setError(`That file is over the ${formatBytes(health.max_upload_mb * 1024 * 1024)} limit.`);
        return;
      }
      setFile(f);
    },
    [health],
  );

  const start = async () => {
    if (!file) return;
    setError(null);
    setProgress({ loaded: 0, total: file.size, started: performance.now() });
    const handle = uploadVideo(file, { ...settings, use_ai: settings.use_ai && aiAvailable }, (loaded, total) =>
      setProgress((p) => (p ? { ...p, loaded, total } : p)),
    );
    handleRef.current = handle;
    try {
      const video = await handle.promise;
      navigate(`/videos/${video.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
      setProgress(null);
    } finally {
      handleRef.current = null;
    }
  };

  const uploading = progress !== null;
  const elapsed = progress ? (performance.now() - progress.started) / 1000 : 0;
  const speed = progress && elapsed > 0.5 ? progress.loaded / elapsed : 0;
  const processing = progress && progress.loaded >= progress.total;

  return (
    <section className="card p-5 sm:p-6" aria-label="Upload a recording">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          if (!uploading) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          if (!uploading) pick(e.dataTransfer.files[0]);
        }}
        onClick={() => !uploading && inputRef.current?.click()}
        onKeyDown={(e) => {
          if ((e.key === "Enter" || e.key === " ") && !uploading) inputRef.current?.click();
        }}
        role="button"
        tabIndex={0}
        className={`flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-4 py-10 text-center transition ${
          dragging ? "border-pink bg-pink/10" : "border-line hover:border-muted/60 hover:bg-surface-2/50"
        } ${uploading ? "pointer-events-none opacity-70" : ""}`}
      >
        <input
          ref={inputRef}
          type="file"
          accept={`video/*,${accept}`}
          className="hidden"
          onChange={(e) => pick(e.target.files?.[0])}
        />
        {file ? (
          <>
            <FileVideo className="mb-3 h-10 w-10 text-teal" />
            <p className="max-w-full truncate font-semibold">{file.name}</p>
            <p className="mt-1 text-sm text-muted">{formatBytes(file.size)} · click to change</p>
          </>
        ) : (
          <>
            <UploadCloud className="mb-3 h-10 w-10 text-pink" />
            <p className="font-semibold">Drop your gameplay recording here</p>
            <p className="mt-1 text-sm text-muted">MP4, MOV, MKV or WebM · streams and long sessions welcome</p>
          </>
        )}
      </div>

      <div className="mt-5 grid gap-5 sm:grid-cols-2">
        <div>
          <p className="label mb-2">Clip length</p>
          <div className="grid grid-cols-3 gap-1 rounded-xl border border-line bg-surface-2 p-1">
            {LENGTHS.map((l) => (
              <button
                key={l.value}
                type="button"
                disabled={uploading}
                onClick={() => setSettings((s) => ({ ...s, length: l.value }))}
                className={`rounded-lg px-2 py-1.5 text-sm transition ${
                  settings.length === l.value ? "bg-gradient-brand font-semibold text-white" : "text-muted hover:text-ink"
                }`}
              >
                {l.label}
                <span className="block text-[10px] opacity-80">{l.hint}</span>
              </button>
            ))}
          </div>
        </div>
        <div className="space-y-3">
          <label className="block">
            <span className="label flex justify-between">
              Max clips <span className="text-ink">{settings.max_clips}</span>
            </span>
            <input
              type="range"
              min={1}
              max={30}
              value={settings.max_clips}
              disabled={uploading}
              onChange={(e) => setSettings((s) => ({ ...s, max_clips: Number(e.target.value) }))}
              className="mt-2 w-full"
            />
          </label>
          <label className="block">
            <span className="label flex justify-between">
              Sensitivity
              <span className="text-ink">
                {settings.sensitivity < 0.34 ? "Only bangers" : settings.sensitivity < 0.67 ? "Balanced" : "Catch everything"}
              </span>
            </span>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={settings.sensitivity}
              disabled={uploading}
              onChange={(e) => setSettings((s) => ({ ...s, sensitivity: Number(e.target.value) }))}
              className="mt-2 w-full"
            />
          </label>
        </div>
      </div>

      <label
        className={`mt-5 flex items-start gap-3 rounded-xl border border-line bg-surface-2 p-3 ${
          aiAvailable ? "cursor-pointer" : "opacity-60"
        }`}
      >
        <input
          type="checkbox"
          className="mt-1 h-4 w-4 accent-pink"
          checked={settings.use_ai && aiAvailable}
          disabled={!aiAvailable || uploading}
          onChange={(e) => setSettings((s) => ({ ...s, use_ai: e.target.checked }))}
        />
        <span className="text-sm">
          <span className="flex items-center gap-1.5 font-semibold">
            <Bot className="h-4 w-4 text-teal" /> AI titles &amp; captions
          </span>
          <span className="text-muted">
            {aiAvailable
              ? "Claude watches each highlight, names it, writes a caption and filters out menus and loading screens."
              : "Add an ANTHROPIC_API_KEY to the server to turn this on. Detection still works without it."}
          </span>
        </span>
      </label>

      {error && (
        <p className="mt-4 rounded-lg border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad" role="alert">
          {error}
        </p>
      )}

      {uploading ? (
        <div className="mt-5 space-y-2">
          <ProgressBar value={progress.total ? progress.loaded / progress.total : 0} />
          <div className="flex items-center justify-between text-sm text-muted">
            <span className="flex items-center gap-2">
              <Loader2 className="h-4 w-4 animate-spin" />
              {processing
                ? "Checking the file…"
                : `Uploading ${formatBytes(progress.loaded)} of ${formatBytes(progress.total)}${
                    speed ? ` · ${formatBytes(speed)}/s` : ""
                  }`}
            </span>
            {!processing && (
              <button type="button" className="btn-icon" aria-label="Cancel upload" onClick={() => handleRef.current?.abort()}>
                <X className="h-4 w-4" />
              </button>
            )}
          </div>
        </div>
      ) : (
        <button type="button" className="btn-primary mt-5 w-full py-3 text-base" disabled={!file} onClick={start}>
          <UploadCloud className="h-5 w-5" /> Find my highlights
        </button>
      )}
    </section>
  );
}
