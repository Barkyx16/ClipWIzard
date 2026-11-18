import { useEffect, useMemo, useRef, useState } from "react";

import { Highlight, Timeline as TimelineData } from "../api";
import { formatTime } from "../lib/format";

interface Props {
  data: TimelineData | null;
  duration: number;
  highlights: Highlight[];
  selectedId: string | null;
  currentTime: number;
  range: { start: number; end: number } | null;
  onSeek: (t: number) => void;
  onSelect: (h: Highlight) => void;
}

const H = 80;

export default function Timeline({
  data,
  duration,
  highlights,
  selectedId,
  currentTime,
  range,
  onSeek,
  onSelect,
}: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{ x: number; t: number } | null>(null);
  const sprites = data?.sprites ?? null;

  // Warm the cache so previews appear instantly.
  useEffect(() => {
    sprites?.sheets.forEach((src) => {
      const img = new Image();
      img.src = src;
    });
  }, [sprites]);

  const preview = (() => {
    if (!hover || !sprites || !sprites.count) return null;
    const perSheet = sprites.cols * sprites.rows;
    const index = Math.min(sprites.count - 1, Math.max(0, Math.floor(hover.t / sprites.interval)));
    const sheet = sprites.sheets[Math.floor(index / perSheet)];
    if (!sheet) return null;
    const within = index % perSheet;
    return {
      src: sheet,
      pos: `-${(within % sprites.cols) * sprites.w}px -${Math.floor(within / sprites.cols) * sprites.h}px`,
    };
  })();

  const path = useMemo(() => {
    const pts = data?.excitement ?? [];
    if (pts.length < 2) return "";
    const step = 1000 / (pts.length - 1);
    let d = `M0,${H}`;
    pts.forEach((v, i) => {
      d += ` L${(i * step).toFixed(2)},${(H - 4 - v * (H - 10)).toFixed(2)}`;
    });
    return d + ` L1000,${H} Z`;
  }, [data]);

  const x = (t: number) => `${(Math.min(Math.max(t / Math.max(duration, 0.001), 0), 1) * 100).toFixed(3)}%`;

  const seekFromEvent = (clientX: number) => {
    const rect = ref.current?.getBoundingClientRect();
    if (!rect) return;
    onSeek(Math.min(Math.max((clientX - rect.left) / rect.width, 0), 1) * duration);
  };

  const ticks = useMemo(() => {
    const count = 6;
    return Array.from({ length: count + 1 }, (_, i) => (duration * i) / count);
  }, [duration]);

  return (
    <div className="relative">
      {hover && (
        <div
          className="pointer-events-none absolute bottom-full z-20 mb-2 -translate-x-1/2 overflow-hidden rounded-lg border border-line bg-bg shadow-2xl"
          style={{
            left: Math.min(
              Math.max(hover.x, (sprites?.w ?? 60) / 2 + 4),
              (ref.current?.clientWidth ?? 0) - (sprites?.w ?? 60) / 2 - 4,
            ),
          }}
        >
          {preview && (
            <div
              style={{
                width: sprites!.w,
                height: sprites!.h,
                backgroundImage: `url(${preview.src})`,
                backgroundPosition: preview.pos,
              }}
            />
          )}
          <p className="px-2 py-0.5 text-center font-mono text-[10px] text-muted">{formatTime(hover.t)}</p>
        </div>
      )}
      <div
        ref={ref}
        className="relative h-20 cursor-pointer select-none overflow-hidden rounded-xl border border-line bg-surface-2"
        onClick={(e) => seekFromEvent(e.clientX)}
        onMouseMove={(e) => {
          const rect = ref.current?.getBoundingClientRect();
          if (!rect) return;
          const frac = Math.min(Math.max((e.clientX - rect.left) / rect.width, 0), 1);
          setHover({ x: e.clientX - rect.left, t: frac * duration });
        }}
        onMouseLeave={() => setHover(null)}
        role="slider"
        aria-label="Video timeline"
        aria-valuemin={0}
        aria-valuemax={Math.round(duration)}
        aria-valuenow={Math.round(currentTime)}
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "ArrowRight") onSeek(Math.min(duration, currentTime + 5));
          if (e.key === "ArrowLeft") onSeek(Math.max(0, currentTime - 5));
        }}
      >
        <svg viewBox={`0 0 1000 ${H}`} preserveAspectRatio="none" className="absolute inset-0 h-full w-full">
          <defs>
            <linearGradient id="exc" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" style={{ stopColor: "var(--color-primary)", stopOpacity: 0.9 }} />
              <stop offset="1" style={{ stopColor: "var(--color-primary-2)", stopOpacity: 0.15 }} />
            </linearGradient>
          </defs>
          {path && <path d={path} fill="url(#exc)" />}
        </svg>

        {highlights.map((h) => (
          <button
            key={h.id}
            type="button"
            title={`#${h.rank + 1} ${h.title}`}
            onClick={(e) => {
              e.stopPropagation();
              onSelect(h);
            }}
            className={`absolute top-0 h-full border-x transition ${
              h.id === selectedId ? "border-accent bg-accent/25" : "border-white/20 bg-white/5 hover:bg-white/15"
            }`}
            style={{ left: x(h.start), width: `calc(${x(h.end)} - ${x(h.start)})` }}
          >
            <span className="absolute left-1 top-1 rounded bg-black/70 px-1 text-[10px] font-bold">{h.rank + 1}</span>
          </button>
        ))}

        {range && (
          <div
            className="pointer-events-none absolute top-0 h-full border-2 border-accent"
            style={{ left: x(range.start), width: `calc(${x(range.end)} - ${x(range.start)})` }}
          />
        )}

        <div
          className="pointer-events-none absolute top-0 h-full w-0.5 bg-white shadow-[0_0_8px_white]"
          style={{ left: x(currentTime) }}
        />
      </div>
      <div className="mt-1 flex justify-between text-[10px] text-dim">
        {ticks.map((t, i) => (
          <span key={i}>{formatTime(t)}</span>
        ))}
      </div>
    </div>
  );
}
