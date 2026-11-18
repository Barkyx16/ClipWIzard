import { useState } from "react";
import { AlertTriangle, Check, Download, Link2, Link2Off, Loader2, Trash2 } from "lucide-react";

import { api, Clip } from "../api";
import { formatBytes, formatTime } from "../lib/format";
import ProgressBar from "./ProgressBar";

const ASPECT_LABEL: Record<string, string> = {
  vertical_blur: "9:16 blur",
  vertical_crop: "9:16 crop",
  vertical_smart: "9:16 smart crop",
  vertical_facecam: "9:16 facecam",
  square: "1:1",
  landscape: "16:9",
};

export default function ExportCard({
  clip,
  title,
  onDelete,
  onChange,
}: {
  clip: Clip;
  title: string;
  onDelete: (c: Clip) => void;
  onChange: (c: Clip) => void;
}) {
  const [sharing, setSharing] = useState(false);
  const [copied, setCopied] = useState(false);

  const share = async () => {
    setSharing(true);
    try {
      const updated = clip.share_url ? clip : await api.shareClip(clip.id);
      onChange(updated);
      if (updated.share_url) {
        await navigator.clipboard.writeText(window.location.origin + updated.share_url).catch(() => undefined);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }
    } finally {
      setSharing(false);
    }
  };

  const unshare = async () => {
    setSharing(true);
    try {
      onChange(await api.unshareClip(clip.id));
    } finally {
      setSharing(false);
    }
  };

  const vertical = clip.options.aspect.startsWith("vertical");
  const ratio = vertical ? "aspect-[9/16]" : clip.options.aspect === "square" ? "aspect-square" : "aspect-video";
  return (
    <div className="card flex flex-col overflow-hidden">
      <div className={`relative ${ratio} max-h-80 w-full bg-bg`}>
        {clip.status === "done" && clip.url ? (
          <video src={clip.url} controls preload="metadata" className="h-full w-full object-contain" />
        ) : clip.status === "failed" ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 p-4 text-center text-sm text-bad">
            <AlertTriangle className="h-6 w-6" />
            Render failed
          </div>
        ) : (
          <div className="flex h-full flex-col items-center justify-center gap-3 p-4 text-sm text-muted">
            <Loader2 className="h-6 w-6 animate-spin text-primary" />
            {clip.status === "queued" ? "Queued…" : `Rendering ${Math.round(clip.progress * 100)}%`}
            <ProgressBar value={clip.progress} className="max-w-40" />
          </div>
        )}
      </div>
      <div className="flex flex-1 flex-col gap-2 p-3">
        <p className="line-clamp-2 text-sm font-semibold" title={title}>
          {title}
        </p>
        <p className="text-xs text-muted">
          {ASPECT_LABEL[clip.options.aspect]} ·{" "}
          {clip.options.kind === "montage"
            ? `${clip.options.segments?.length ?? 0} moments · ${formatTime(clip.end - clip.start)}`
            : `${formatTime(clip.start)}–${formatTime(clip.end)}`}
          {clip.size_bytes ? ` · ${formatBytes(clip.size_bytes)}` : ""}
        </p>
        {clip.error && <p className="line-clamp-3 text-xs text-bad">{clip.error}</p>}
        {clip.warning && <p className="line-clamp-2 text-xs text-warn">{clip.warning}</p>}
        {clip.share_url && (
          <p className="flex items-center justify-between gap-2 text-xs text-accent">
            <a href={clip.share_url} target="_blank" rel="noreferrer" className="truncate hover:underline">
              {copied ? "Link copied!" : "Shared link is on"}
            </a>
            <button
              type="button"
              className="inline-flex items-center gap-1 text-muted hover:text-bad"
              onClick={unshare}
              disabled={sharing}
            >
              <Link2Off className="h-3.5 w-3.5" /> Stop sharing
            </button>
          </p>
        )}
        {clip.transcript && (
          <details className="text-xs text-muted">
            <summary className="cursor-pointer select-none">Transcript</summary>
            <p className="mt-1 max-h-24 overflow-y-auto whitespace-pre-wrap">{clip.transcript}</p>
          </details>
        )}
        <div className="mt-auto flex gap-2 pt-1">
          {clip.download_url && (
            <a href={clip.download_url} className="btn-primary flex-1 py-2" download>
              <Download className="h-4 w-4" /> Download
            </a>
          )}
          {clip.status === "done" && (
            <button
              type="button"
              className={`btn-icon ${clip.share_url ? "border-accent text-accent" : ""}`}
              aria-label={clip.share_url ? "Copy share link" : "Create share link"}
              title={clip.share_url ? "Copy share link" : "Share: create a link anyone can open"}
              disabled={sharing}
              onClick={share}
            >
              {copied ? <Check className="h-4 w-4 text-good" /> : <Link2 className="h-4 w-4" />}
            </button>
          )}
          {(clip.status === "done" || clip.status === "failed") && (
            <button type="button" className="btn-icon" aria-label="Delete clip" onClick={() => onDelete(clip)}>
              <Trash2 className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
