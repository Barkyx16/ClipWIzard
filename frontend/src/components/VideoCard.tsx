import { Link } from "react-router-dom";
import { AlertTriangle, Clapperboard, Trash2 } from "lucide-react";

import { isBusy, Video } from "../api";
import { formatBytes, formatTime, timeAgo } from "../lib/format";
import ProgressBar from "./ProgressBar";

export default function VideoCard({ video, onDelete }: { video: Video; onDelete: (v: Video) => void }) {
  const busy = isBusy(video);
  return (
    <div className="card group relative overflow-hidden transition hover:border-muted/50">
      <Link to={`/videos/${video.id}`} className="block focus-visible:outline-2 focus-visible:outline-accent">
        <div className="relative aspect-video bg-surface-2">
          {video.thumbnail_url ? (
            <img src={video.thumbnail_url} alt="" className="h-full w-full object-cover" loading="lazy" />
          ) : (
            <div className="flex h-full items-center justify-center text-dim">
              <Clapperboard className="h-10 w-10" />
            </div>
          )}
          {video.duration ? (
            <span className="absolute bottom-2 right-2 rounded-md bg-black/70 px-1.5 py-0.5 text-xs font-medium">
              {formatTime(video.duration)}
            </span>
          ) : null}
        </div>
        <div className="space-y-2 p-4">
          <p className="truncate font-semibold" title={video.name}>
            {video.name}
          </p>
          {busy ? (
            <>
              <ProgressBar value={video.progress} />
              <p className="text-xs text-muted">{video.stage ?? "Queued"}…</p>
            </>
          ) : video.status === "failed" ? (
            <p className="flex items-center gap-1.5 text-xs text-bad">
              <AlertTriangle className="h-3.5 w-3.5" />{" "}
              {video.stage === "Import failed" ? "Import failed" : "Analysis failed"}
            </p>
          ) : (
            <p className="text-xs text-muted">
              {formatBytes(video.size_bytes)} · {timeAgo(video.created_at)}
            </p>
          )}
        </div>
      </Link>
      {!busy && (
        <button
          type="button"
          className="btn-icon absolute right-2 top-2 bg-black/60 opacity-0 transition group-hover:opacity-100 focus:opacity-100"
          aria-label={`Delete ${video.name}`}
          onClick={() => onDelete(video)}
        >
          <Trash2 className="h-4 w-4" />
        </button>
      )}
    </div>
  );
}
