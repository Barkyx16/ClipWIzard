import { categoryStyle } from "../lib/format";

export default function CategoryBadge({ category }: { category: string }) {
  const { color, emoji } = categoryStyle(category);
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold"
      style={{ color, backgroundColor: `${color}1f`, border: `1px solid ${color}40` }}
    >
      <span aria-hidden>{emoji}</span>
      {category}
    </span>
  );
}

export function ScoreBadge({ score }: { score: number }) {
  const s = Math.round(score);
  const color = s >= 80 ? "#ff3d8b" : s >= 55 ? "#ff9a3c" : "#a59cc4";
  return (
    <span
      className="inline-flex h-7 min-w-9 items-center justify-center rounded-lg px-1.5 font-display text-lg leading-none"
      style={{ color, backgroundColor: `${color}1f` }}
      title="Hype score"
    >
      {s}
    </span>
  );
}
