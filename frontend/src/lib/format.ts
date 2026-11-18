export function formatTime(seconds: number, precise = false): string {
  if (!Number.isFinite(seconds) || seconds < 0) seconds = 0;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  const sec = precise ? s.toFixed(1).padStart(4, "0") : String(Math.floor(s)).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
}

/** Parses "1:23", "1:02:03.5" or "83.5" into seconds. Returns null if invalid. */
export function parseTime(text: string): number | null {
  const parts = text.trim().split(":");
  if (parts.length > 3 || parts.some((p) => p === "" || Number.isNaN(Number(p)))) return null;
  return parts.reduce((acc, p) => acc * 60 + Number(p), 0);
}

export function formatBytes(bytes: number): string {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
  return `${(bytes / 1024 ** i).toFixed(i >= 2 ? 1 : 0)} ${units[i]}`;
}

export function timeAgo(epochSeconds: number): string {
  const diff = Date.now() / 1000 - epochSeconds;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export const CATEGORY_STYLE: Record<string, { color: string; emoji: string }> = {
  Shootout: { color: "#ff5c6c", emoji: "🔫" },
  "Police Chase": { color: "#4d8bff", emoji: "🚓" },
  "Car Chase": { color: "#2de2e6", emoji: "🏎️" },
  Chase: { color: "#2de2e6", emoji: "🏎️" },
  Explosion: { color: "#ff9a3c", emoji: "💥" },
  "Big Impact": { color: "#ff9a3c", emoji: "💥" },
  "Car Crash": { color: "#ffb84d", emoji: "🚗" },
  Stunt: { color: "#b56cff", emoji: "🛞" },
  Heist: { color: "#4ade80", emoji: "💰" },
  "Wanted Escape": { color: "#7aa2ff", emoji: "⭐" },
  "Funny Moment": { color: "#ffe14d", emoji: "😂" },
  Fail: { color: "#ff7ac6", emoji: "🤦" },
  "Clutch Play": { color: "#4ade80", emoji: "🎯" },
  Scenic: { color: "#7be3ff", emoji: "🌅" },
  "Hype Moment": { color: "#ff3d8b", emoji: "🔥" },
  Action: { color: "#a59cc4", emoji: "⚡" },
};

export function categoryStyle(category: string) {
  return CATEGORY_STYLE[category] ?? CATEGORY_STYLE.Action;
}
