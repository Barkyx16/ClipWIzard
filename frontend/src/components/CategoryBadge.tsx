import { categoryStyle } from "../lib/format";

const tint = (color: string, pct: number) => `color-mix(in srgb, ${color} ${pct}%, transparent)`;

export default function CategoryBadge({ category }: { category: string }) {
  const { color, emoji } = categoryStyle(category);
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold"
      style={{ color, backgroundColor: tint(color, 12), border: `1px solid ${tint(color, 25)}` }}
    >
      <span aria-hidden>{emoji}</span>
      {category}
    </span>
  );
}

export function ScoreBadge({ score }: { score: number }) {
  const s = Math.round(score);
  const color = s >= 80 ? "var(--color-primary)" : s >= 55 ? "var(--color-primary-2)" : "var(--color-muted)";
  return (
    <span
      className="inline-flex h-7 min-w-9 items-center justify-center rounded-lg px-1.5 font-display text-lg leading-none"
      style={{ color, backgroundColor: tint(color, 12) }}
      title="Hype score"
    >
      {s}
    </span>
  );
}
