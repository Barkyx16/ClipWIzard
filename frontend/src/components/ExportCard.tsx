import { AlertTriangle, Download, Loader2, Trash2 } from "lucide-react";

import { Clip } from "../api";
import { formatBytes, formatTime } from "../lib/format";
import ProgressBar from "./ProgressBar";

const ASPECT_LABEL: Record<string, string> = {
  vertical_blur: "9:16 blur",
  vertical_crop: "9:16 crop",
  square: "1:1",
  landscape: "16:9",
};

export default function ExportCard({ clip, title, onDelete }: { clip: Clip; title: string; onDelete: (c: Clip) => void }) {
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
          {ASPECT_LABEL[clip.options.aspect]} · {formatTime(clip.start)}–{formatTime(clip.end)}
          {clip.size_bytes ? ` · ${formatBytes(clip.size_bytes)}` : ""}
        </p>
        {clip.error && <p className="line-clamp-3 text-xs text-bad">{clip.error}</p>}
        <div className="mt-auto flex gap-2 pt-1">
          {clip.download_url && (
            <a href={clip.download_url} className="btn-primary flex-1 py-2" download>
              <Download className="h-4 w-4" /> Download
            </a>
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
