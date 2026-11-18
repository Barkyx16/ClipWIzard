import { Bot } from "lucide-react";

import { Highlight } from "../api";
import { formatTime } from "../lib/format";
import CategoryBadge, { ScoreBadge } from "./CategoryBadge";

export default function HighlightCard({
  h,
  selected,
  onSelect,
}: {
  h: Highlight;
  selected: boolean;
  onSelect: (h: Highlight) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onSelect(h)}
      className={`flex w-full gap-3 rounded-xl border p-2 text-left transition focus-visible:outline-2 focus-visible:outline-teal ${
        selected ? "border-teal bg-teal/10" : "border-line bg-surface-2/60 hover:border-muted/50"
      }`}
    >
      <div className="relative aspect-video w-28 shrink-0 overflow-hidden rounded-lg bg-bg">
        {h.thumbnail_url && <img src={h.thumbnail_url} alt="" className="h-full w-full object-cover" loading="lazy" />}
        <span className="absolute left-1 top-1 rounded bg-black/70 px-1 text-[10px] font-bold">#{h.rank + 1}</span>
        <span className="absolute bottom-1 right-1 rounded bg-black/70 px-1 text-[10px]">
          {Math.round(h.end - h.start)}s
        </span>
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-2">
          <p className="line-clamp-2 text-sm font-semibold leading-snug">{h.title}</p>
          <ScoreBadge score={h.score} />
        </div>
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs text-muted">
          <CategoryBadge category={h.category} />
          <span>
            {formatTime(h.start)}–{formatTime(h.end)}
          </span>
          {h.ai_enriched && <Bot className="h-3.5 w-3.5 text-teal" aria-label="AI enriched" />}
        </div>
      </div>
    </button>
  );
}
