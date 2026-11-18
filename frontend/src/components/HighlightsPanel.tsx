import { useMemo, useState } from "react";
import { Clapperboard, Layers, Loader2, X } from "lucide-react";

import { Highlight } from "../api";
import { formatTime } from "../lib/format";
import HighlightCard from "./HighlightCard";

export type MontageOrder = "as_given" | "timeline" | "score";
export type Transition = "fade" | "fadeblack" | "slideleft" | "cut";

interface Props {
  highlights: Highlight[];
  selectedId: string | null;
  onSelect: (h: Highlight) => void;
  onExportTop: () => void;
  onMontage: (ids: string[], order: MontageOrder, transition: Transition) => Promise<boolean>;
}

const TRANSITIONS: { value: Transition; label: string }[] = [
  { value: "fade", label: "Crossfade" },
  { value: "fadeblack", label: "Fade to black" },
  { value: "slideleft", label: "Slide" },
  { value: "cut", label: "Hard cut" },
];

export default function HighlightsPanel({ highlights, selectedId, onSelect, onExportTop, onMontage }: Props) {
  const [picking, setPicking] = useState(false);
  const [picked, setPicked] = useState<string[]>([]);
  const [order, setOrder] = useState<MontageOrder>("timeline");
  const [transition, setTransition] = useState<Transition>("fade");
  const [busy, setBusy] = useState(false);

  const total = useMemo(
    () =>
      picked.reduce((sum, id) => {
        const h = highlights.find((x) => x.id === id);
        return sum + (h ? h.end - h.start : 0);
      }, 0),
    [picked, highlights],
  );

  const startPicking = () => {
    // Pre-select the five best moments.
    setPicked(highlights.slice(0, 5).map((h) => h.id));
    setPicking(true);
  };

  const toggle = (h: Highlight) =>
    setPicked((list) => (list.includes(h.id) ? list.filter((x) => x !== h.id) : [...list, h.id]));

  const render = async () => {
    setBusy(true);
    const ok = await onMontage(picked, order, transition);
    setBusy(false);
    if (ok) setPicking(false);
  };

  return (
    <section className="card p-4" aria-labelledby="highlights-heading">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 id="highlights-heading" className="font-display text-2xl tracking-wide">
          {picking ? "Pick moments" : "Highlights"}
        </h2>
        {highlights.length > 0 &&
          (picking ? (
            <button
              type="button"
              className="btn-icon h-8 w-8"
              aria-label="Cancel montage"
              onClick={() => setPicking(false)}
            >
              <X className="h-4 w-4" />
            </button>
          ) : (
            <div className="flex gap-1.5">
              {highlights.length > 1 && (
                <button type="button" className="btn-ghost px-3 py-1.5 text-xs" onClick={startPicking}>
                  <Clapperboard className="h-4 w-4" /> Montage
                </button>
              )}
              <button type="button" className="btn-ghost px-3 py-1.5 text-xs" onClick={onExportTop}>
                <Layers className="h-4 w-4" /> Top {Math.min(5, highlights.length)}
              </button>
            </div>
          ))}
      </div>

      {highlights.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted">
          No big moments found. Try a re-scan with higher sensitivity, or trim a custom clip below.
        </p>
      ) : (
        <div className="max-h-[420px] space-y-2 overflow-y-auto pr-1">
          {highlights.map((h) =>
            picking ? (
              <HighlightCard
                key={h.id}
                h={h}
                selected={false}
                checked={picked.includes(h.id)}
                order={order === "as_given" && picked.includes(h.id) ? picked.indexOf(h.id) + 1 : undefined}
                onSelect={toggle}
              />
            ) : (
              <HighlightCard key={h.id} h={h} selected={h.id === selectedId} onSelect={onSelect} />
            ),
          )}
        </div>
      )}

      {picking && (
        <div className="mt-3 space-y-3 border-t border-line pt-3">
          <div className="grid grid-cols-2 gap-2">
            <label className="block">
              <span className="label">Order</span>
              <select className="input mt-1" value={order} onChange={(e) => setOrder(e.target.value as MontageOrder)}>
                <option value="timeline">As they happened</option>
                <option value="score">Best first</option>
                <option value="as_given">Order I picked</option>
              </select>
            </label>
            <label className="block">
              <span className="label">Transition</span>
              <select
                className="input mt-1"
                value={transition}
                onChange={(e) => setTransition(e.target.value as Transition)}
              >
                {TRANSITIONS.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <p className="text-xs text-muted">Uses the format, title and caption settings from the editor below.</p>
          <button
            type="button"
            className="btn-primary w-full"
            disabled={picked.length < 2 || busy || total > 600}
            onClick={render}
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Clapperboard className="h-4 w-4" />}
            {picked.length < 2
              ? "Pick at least 2 moments"
              : total > 600
                ? "Too long (max 10 min)"
                : `Render montage · ${picked.length} moments · ${formatTime(total)}`}
          </button>
        </div>
      )}
    </section>
  );
}
