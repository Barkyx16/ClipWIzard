import { Loader2, RotateCcw } from "lucide-react";

import { formatTime } from "../lib/format";
import { Phrase } from "../lib/captions";

export interface CaptionReviewState {
  start: number;
  end: number;
  status: "running" | "done" | "failed";
  error: string | null;
  phrases: Phrase[];
}

interface Props {
  review: CaptionReviewState | null;
  stale: boolean;
  onStart: () => void;
  onEdit: (index: number, text: string) => void;
  onReset: () => void;
}

export default function CaptionReview({ review, stale, onStart, onEdit, onReset }: Props) {
  if (!review || stale) {
    return (
      <div className="flex items-center justify-between gap-2 text-xs">
        <span className="text-muted">
          {stale ? "You changed the clip range, so the reviewed words no longer match." : "Want to fix misheard words?"}
        </span>
        <button type="button" className="btn-ghost shrink-0 px-2.5 py-1 text-xs" onClick={onStart}>
          Review words
        </button>
      </div>
    );
  }
  if (review.status === "running") {
    return (
      <p className="flex items-center gap-2 text-xs text-muted">
        <Loader2 className="h-3.5 w-3.5 animate-spin" /> Listening to the clip…
      </p>
    );
  }
  if (review.status === "failed") {
    return (
      <div className="flex items-center justify-between gap-2 text-xs">
        <span className="text-bad">{review.error ?? "Couldn't transcribe this clip"}</span>
        <button type="button" className="btn-ghost shrink-0 px-2.5 py-1 text-xs" onClick={onStart}>
          Try again
        </button>
      </div>
    );
  }
  if (!review.phrases.length) {
    return <p className="text-xs text-muted">No speech found in this clip.</p>;
  }
  const edited = review.phrases.some((p) => p.text.trim() !== p.original);
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <p className="label">Words ({review.phrases.length} lines)</p>
        {edited && (
          <button
            type="button"
            className="inline-flex items-center gap-1 text-xs text-muted hover:text-ink"
            onClick={onReset}
          >
            <RotateCcw className="h-3 w-3" /> Undo edits
          </button>
        )}
      </div>
      <div className="max-h-56 space-y-1.5 overflow-y-auto pr-1">
        {review.phrases.map((p, i) => (
          <label key={i} className="flex items-center gap-2">
            <span className="w-11 shrink-0 font-mono text-[10px] text-dim">{formatTime(review.start + p.start, true)}</span>
            <input
              className={`input py-1.5 ${p.text.trim() !== p.original ? "border-accent" : ""}`}
              value={p.text}
              maxLength={80}
              placeholder="(removed)"
              onChange={(e) => onEdit(i, e.target.value)}
              aria-label={`Caption line ${i + 1}`}
            />
          </label>
        ))}
      </div>
      <p className="text-[11px] text-dim">Clear a line to remove it. Your edits are used when you export.</p>
    </div>
  );
}
