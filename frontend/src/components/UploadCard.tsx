import { useCallback, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Bot, FileVideo, Files, Link2, Loader2, UploadCloud, X } from "lucide-react";

import { AnalyzeSettings, api, ApiError, ClipLength, Health, UploadHandle, uploadVideo } from "../api";
import { formatBytes } from "../lib/format";
import ProgressBar from "./ProgressBar";

const LENGTHS: { value: ClipLength; label: string; hint: string }[] = [
  { value: "short", label: "Short", hint: "12–30s" },
  { value: "medium", label: "Medium", hint: "25–60s" },
  { value: "long", label: "Long", hint: "45–90s" },
];

const MAX_FILES = 10;
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export default function UploadCard({ health, onUploaded }: { health: Health | null; onUploaded?: () => void }) {
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const handleRef = useRef<UploadHandle | null>(null);
  const [mode, setMode] = useState<"file" | "link">("file");
  const [link, setLink] = useState("");
  const [importing, setImporting] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [current, setCurrent] = useState<{ index: number; total: number } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const cancelled = useRef(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<{
    loaded: number;
    total: number;
    started: number;
    base: number | null;
  } | null>(null);
  const [uploadStatus, setUploadStatus] = useState<string | null>(null);
  const [settings, setSettings] = useState<AnalyzeSettings>({
    length: "short",
    max_clips: 12,
    sensitivity: 0.5,
    use_ai: true,
  });

  const aiAvailable = health?.ai_enabled ?? false;
  const accept = (health?.allowed_extensions ?? [".mp4", ".mov", ".mkv", ".webm"]).join(",");

  const pick = useCallback(
    (list: FileList | null | undefined) => {
      if (!list?.length) return;
      setError(null);
      setNotice(null);
      const ok: File[] = [];
      const problems: string[] = [];
      for (const f of Array.from(list).slice(0, MAX_FILES)) {
        const ext = "." + (f.name.split(".").pop() ?? "").toLowerCase();
        if (health && !health.allowed_extensions.includes(ext)) {
          problems.push(`${f.name}: file type not supported (try ${health.allowed_extensions.join(", ")})`);
        } else if (health && f.size > health.max_upload_mb * 1024 * 1024) {
          problems.push(`${f.name}: over the ${formatBytes(health.max_upload_mb * 1024 * 1024)} limit`);
        } else {
          ok.push(f);
        }
      }
      if (list.length > MAX_FILES) problems.push(`Only the first ${MAX_FILES} files were added`);
      if (problems.length) setError(problems.join(". ") + ".");
      if (ok.length) setFiles(ok);
    },
    [health],
  );

  /** Uploads one file; waits and retries while the workspace is at its processing limit. */
  const uploadOne = async (file: File) => {
    for (;;) {
      setProgress({ loaded: 0, total: file.size, started: performance.now(), base: null });
      setUploadStatus(null);
      const handle = uploadVideo(
        file,
        { ...settings, use_ai: settings.use_ai && aiAvailable },
        {
          // `base` is where this attempt started, so resumed uploads report a real speed.
          onProgress: (loaded, total) =>
            setProgress((p) =>
              p
                ? p.base === null
                  ? { ...p, loaded, total, base: loaded, started: performance.now() }
                  : { ...p, loaded, total }
                : p,
            ),
          onStatus: setUploadStatus,
        },
      );
      handleRef.current = handle;
      try {
        return await handle.promise;
      } catch (e) {
        if (e instanceof ApiError && e.status === 429 && !cancelled.current) {
          setProgress({ loaded: 0, total: file.size, started: performance.now(), base: 0 });
          setUploadStatus(`${e.message.replace(/\.$/, "")}. Retrying automatically…`);
          await sleep(10_000);
          if (cancelled.current) throw new ApiError(-1, "Upload cancelled");
          continue;
        }
        throw e;
      } finally {
        handleRef.current = null;
      }
    }
  };

  const start = async () => {
    if (!files.length) return;
    setError(null);
    setNotice(null);
    cancelled.current = false;
    const done: string[] = [];
    try {
      for (let i = 0; i < files.length; i++) {
        setCurrent({ index: i, total: files.length });
        const video = await uploadOne(files[i]);
        done.push(video.id);
      }
      if (done.length === 1) {
        navigate(`/videos/${done[0]}`);
        return;
      }
      setNotice(`Uploaded ${done.length} recordings. They're being analysed in Your sessions below.`);
      setFiles([]);
      onUploaded?.();
    } catch (e) {
      const wasCancelled = e instanceof ApiError && e.status === -1;
      const name = files[done.length]?.name;
      setError(
        wasCancelled
          ? done.length
            ? `Stopped after ${done.length} of ${files.length} files.`
            : null
          : `${name ? `${name}: ` : ""}${e instanceof Error ? e.message : "Upload failed"}. ` +
              "Pick the same file again to resume where it stopped.",
      );
      if (done.length) {
        setFiles(files.slice(done.length));
        onUploaded?.();
      }
    } finally {
      setProgress(null);
      setUploadStatus(null);
      setCurrent(null);
    }
  };

  const startImport = async () => {
    setError(null);
    setImporting(true);
    try {
      const video = await api.importLink(link.trim(), { ...settings, use_ai: settings.use_ai && aiAvailable });
      navigate(`/videos/${video.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Import failed");
      setImporting(false);
    }
  };

  const uploading = progress !== null || importing;
  const elapsed = progress ? (performance.now() - progress.started) / 1000 : 0;
  const speed = progress && elapsed > 0.5 ? (progress.loaded - (progress.base ?? 0)) / elapsed : 0;
  const processing = progress && progress.loaded >= progress.total;

  return (
    <section className="card p-5 sm:p-6" aria-label="Upload a recording">
      <div className="mb-4 grid grid-cols-2 gap-1 rounded-xl border border-line bg-surface-2 p-1" role="tablist">
        {(
          [
            ["file", "Upload file", UploadCloud],
            ["link", "Paste link", Link2],
          ] as const
        ).map(([value, label, Icon]) => (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={mode === value}
            disabled={uploading}
            onClick={() => {
              setMode(value);
              setError(null);
            }}
            className={`flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm transition ${
              mode === value ? "bg-surface font-semibold text-ink shadow" : "text-muted hover:text-ink"
            }`}
          >
            <Icon className="h-4 w-4" /> {label}
          </button>
        ))}
      </div>

      {mode === "link" ? (
        <div className="rounded-xl border-2 border-dashed border-line px-4 py-6">
          <label htmlFor="import-link" className="label">
            Video link
          </label>
          <input
            id="import-link"
            className="input mt-2"
            type="url"
            inputMode="url"
            placeholder="https://www.twitch.tv/videos/…"
            value={link}
            disabled={uploading}
            onChange={(e) => setLink(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && link.trim() && startImport()}
          />
          <p className="mt-2 text-xs text-muted">
            {health?.import_sites?.length
              ? `Works with ${health.import_sites.join(", ")} and direct .mp4 links.`
              : "Works with YouTube, Twitch, Kick, Medal and direct .mp4 links."}{" "}
            Only import videos you have the rights to use.
          </p>
        </div>
      ) : (
        <div
          onDragOver={(e) => {
            e.preventDefault();
            if (!uploading) setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            if (!uploading) pick(e.dataTransfer.files);
          }}
          onClick={() => !uploading && inputRef.current?.click()}
          onKeyDown={(e) => {
            if ((e.key === "Enter" || e.key === " ") && !uploading) inputRef.current?.click();
          }}
          role="button"
          tabIndex={0}
          className={`flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-4 py-10 text-center transition ${
            dragging ? "border-primary bg-primary/10" : "border-line hover:border-muted/60 hover:bg-surface-2/50"
          } ${uploading ? "pointer-events-none opacity-70" : ""}`}
        >
          <input
            ref={inputRef}
            type="file"
            accept={`video/*,${accept}`}
            multiple
            className="hidden"
            onChange={(e) => {
              pick(e.target.files);
              e.target.value = "";
            }}
          />
          {files.length === 1 ? (
            <>
              <FileVideo className="mb-3 h-10 w-10 text-accent" />
              <p className="max-w-full truncate font-semibold">{files[0].name}</p>
              <p className="mt-1 text-sm text-muted">{formatBytes(files[0].size)} · click to change</p>
            </>
          ) : files.length > 1 ? (
            <>
              <Files className="mb-3 h-10 w-10 text-accent" />
              <p className="font-semibold">{files.length} recordings</p>
              <p className="mt-1 max-w-full truncate text-sm text-muted">
                {files
                  .slice(0, 3)
                  .map((f) => f.name)
                  .join(", ")}
                {files.length > 3 ? ` +${files.length - 3} more` : ""}
              </p>
              <p className="mt-1 text-xs text-dim">
                {formatBytes(files.reduce((n, f) => n + f.size, 0))} total · click to change
              </p>
            </>
          ) : (
            <>
              <UploadCloud className="mb-3 h-10 w-10 text-primary" />
              <p className="font-semibold">Drop your gameplay recordings here</p>
              <p className="mt-1 text-sm text-muted">MP4, MOV, MKV or WebM · streams and long sessions welcome</p>
            </>
          )}
        </div>
      )}

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
                  settings.length === l.value
                    ? "bg-gradient-brand font-semibold text-on-primary"
                    : "text-muted hover:text-ink"
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
                {settings.sensitivity < 0.34
                  ? "Only bangers"
                  : settings.sensitivity < 0.67
                    ? "Balanced"
                    : "Catch everything"}
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
          className="mt-1 h-4 w-4 accent-primary"
          checked={settings.use_ai && aiAvailable}
          disabled={!aiAvailable || uploading}
          onChange={(e) => setSettings((s) => ({ ...s, use_ai: e.target.checked }))}
        />
        <span className="text-sm">
          <span className="flex items-center gap-1.5 font-semibold">
            <Bot className="h-4 w-4 text-accent" /> AI titles &amp; captions
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
      {notice && (
        <p className="mt-4 rounded-lg border border-good/40 bg-good/10 px-3 py-2 text-sm text-good" role="status">
          {notice}
        </p>
      )}

      {importing ? (
        <p className="mt-5 flex items-center justify-center gap-2 text-sm text-muted">
          <Loader2 className="h-4 w-4 animate-spin" /> Starting import…
        </p>
      ) : progress ? (
        <div className="mt-5 space-y-2">
          <ProgressBar value={progress.total ? progress.loaded / progress.total : 0} />
          <div className="flex items-center justify-between text-sm text-muted">
            <span className="flex items-center gap-2">
              <Loader2 className="h-4 w-4 animate-spin" />
              {processing
                ? "Checking the file…"
                : (current && current.total > 1 ? `File ${current.index + 1} of ${current.total} · ` : "") +
                  (uploadStatus ??
                    `Uploading ${formatBytes(progress.loaded)} of ${formatBytes(progress.total)}${
                      speed ? ` · ${formatBytes(speed)}/s` : ""
                    }`)}
            </span>
            {!processing && (
              <button
                type="button"
                className="btn-icon"
                aria-label="Cancel upload"
                onClick={() => {
                  cancelled.current = true;
                  handleRef.current?.abort();
                }}
              >
                <X className="h-4 w-4" />
              </button>
            )}
          </div>
        </div>
      ) : (
        <button
          type="button"
          className="btn-primary mt-5 w-full py-3 text-base"
          disabled={mode === "file" ? !files.length : link.trim().length < 8}
          onClick={mode === "file" ? start : startImport}
        >
          {mode === "file" ? <UploadCloud className="h-5 w-5" /> : <Link2 className="h-5 w-5" />} Find my highlights
        </button>
      )}
    </section>
  );
}
