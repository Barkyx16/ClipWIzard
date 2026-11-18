import { useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";

import { Video } from "../api";
import { formatTime } from "../lib/format";
import ProgressBar from "./ProgressBar";

const TIPS = [
  "Tip: vertical blur-fill keeps the whole frame visible, perfect for driving clips.",
  "Tip: use the crosshair buttons to set the clip start/end from the playhead.",
  "Tip: lower the sensitivity to keep only the biggest moments.",
  "Tip: burn the title in. Clips with on-screen hooks tend to hold viewers longer.",
];

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

export default function AnalyzingState({ video }: { video: Video }) {
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
