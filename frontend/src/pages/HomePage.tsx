import { useCallback, useEffect, useRef, useState } from "react";
import { AudioWaveform, Crosshair, Scissors, Search, Wand2 } from "lucide-react";

import { api, Health, isBusy, Video } from "../api";
import UploadCard from "../components/UploadCard";
import Faq from "../components/Faq";
import { notify } from "../lib/notify";
import VideoCard from "../components/VideoCard";
import { usePolling } from "../lib/usePolling";

const STEPS = [
  {
    icon: AudioWaveform,
    title: "Upload a session",
    body: "Drop in a raw recording or a whole stream VOD. Hours long is fine.",
  },
  {
    icon: Crosshair,
    title: "We find the chaos",
    body: "Gunfire, explosions, crashes, chases and hype reactions get detected and ranked.",
  },
  {
    icon: Scissors,
    title: "Export vertical clips",
    body: "Trim, add a title and export 9:16 clips ready for TikTok, Shorts and Reels.",
  },
];

export default function HomePage() {
  const [health, setHealth] = useState<Health | null>(null);
  const [videos, setVideos] = useState<Video[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  const busyIds = useRef<Set<string>>(new Set());
  const load = useCallback(async () => {
    try {
      const list = await api.videos();
      for (const v of list) {
        if (busyIds.current.has(v.id) && v.status === "ready") {
          notify("Highlights ready", `${v.name} is ready to clip`, `/videos/${v.id}`);
        }
      }
      busyIds.current = new Set(list.filter(isBusy).map((v) => v.id));
      setVideos(list);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not reach the server");
    }
  }, []);

  useEffect(() => {
    api
      .health()
      .then(setHealth)
      .catch(() => setHealth(null));
    load();
  }, [load]);

  const anyBusy = videos?.some(isBusy) ?? false;
  usePolling(load, 2000, anyBusy);

  const remove = async (v: Video) => {
    if (!confirm(`Delete "${v.name}" and all of its clips?`)) return;
    try {
      await api.deleteVideo(v.id);
      setVideos((list) => list?.filter((x) => x.id !== v.id) ?? null);
    } catch (e) {
      alert(e instanceof Error ? e.message : "Delete failed");
    }
  };

  return (
    <div className="space-y-14">
      <section className="grid items-center gap-10 lg:grid-cols-[1.1fr_1fr]">
        <div>
          <p className="mb-4 inline-flex items-center gap-2 rounded-full border border-primary/40 bg-primary/10 px-3 py-1 text-xs font-semibold text-primary">
            <Wand2 className="h-3.5 w-3.5" /> Built for GTA 6 clippers
          </p>
          <h1 className="font-display text-6xl leading-[0.95] tracking-wide sm:text-7xl lg:text-8xl">
            Hours of gameplay.
            <br />
            <span className="text-gradient">Minutes of fire.</span>
          </h1>
          <p className="mt-6 max-w-xl text-lg text-muted">
            ClipWizard scans your sessions for the shootouts, wipeouts and getaways worth posting, then cuts them into
            ready-to-share vertical clips. No scrubbing through four hours of footage.
          </p>
          <ol className="mt-8 grid gap-4 sm:grid-cols-3">
            {STEPS.map((s, i) => (
              <li key={s.title} className="rounded-xl border border-line/80 bg-surface/50 p-4">
                <s.icon className="mb-2 h-5 w-5 text-accent" />
                <p className="text-sm font-semibold">
                  {i + 1}. {s.title}
                </p>
                <p className="mt-1 text-xs text-muted">{s.body}</p>
              </li>
            ))}
          </ol>
        </div>
        <UploadCard health={health} onUploaded={load} />
      </section>

      <section aria-labelledby="projects-heading">
        <div className="mb-4 flex items-end justify-between">
          <h2 id="projects-heading" className="font-display text-4xl tracking-wide">
            Your sessions
          </h2>
          {videos && videos.length > 4 ? (
            <label className="relative w-56">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-dim" />
              <input
                className="input pl-9"
                placeholder="Search sessions"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                aria-label="Search sessions"
              />
            </label>
          ) : (
            videos && videos.length > 0 && <span className="text-sm text-muted">{videos.length} uploaded</span>
          )}
        </div>
        {error && (
          <p className="rounded-lg border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad" role="alert">
            {error}
          </p>
        )}
        {videos === null && !error ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="card aspect-[4/3] animate-pulse" />
            ))}
          </div>
        ) : videos && videos.length === 0 ? (
          <div className="card px-6 py-12 text-center text-muted">
            No sessions yet. Upload a recording above to get your first highlights.
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {videos
              ?.filter((v) => !query.trim() || v.name.toLowerCase().includes(query.trim().toLowerCase()))
              .map((v) => (
                <VideoCard key={v.id} video={v} onDelete={remove} />
              ))}
          </div>
        )}
      </section>

      <Faq health={health} />
    </div>
  );
}
