export default function ProgressBar({ value, className = "" }: { value: number; className?: string }) {
  const pct = Math.round(Math.min(1, Math.max(0, value)) * 100);
  return (
    <div
      className={`h-2 w-full overflow-hidden rounded-full bg-surface-2 ${className}`}
      role="progressbar"
      aria-valuenow={pct}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div
        className="bg-gradient-brand h-full rounded-full transition-[width] duration-500"
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}
