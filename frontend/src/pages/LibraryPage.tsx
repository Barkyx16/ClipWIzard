import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Loader2, Search } from "lucide-react";

import { api, Clip, LibraryClip } from "../api";
import ExportCard from "../components/ExportCard";

export default function LibraryPage() {
  const [clips, setClips] = useState<LibraryClip[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    document.title = "My clips · ClipWizard";
    api
      .library()
      .then(setClips)
      .catch((e) => setError(e instanceof Error ? e.message : "Couldn't load your clips"));
    return () => void (document.title = "ClipWizard");
  }, []);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (clips ?? []).filter(
      (c) => !q || c.title.toLowerCase().includes(q) || c.video_name.toLowerCase().includes(q),
    );
  }, [clips, query]);

  const remove = async (c: Clip) => {
    if (!confirm("Delete this clip?")) return;
    try {
      await api.deleteClip(c.id);
      setClips((list) => list?.filter((x) => x.id !== c.id) ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    }
  };

  const update = (c: Clip) => setClips((list) => list?.map((x) => (x.id === c.id ? { ...x, ...c } : x)) ?? null);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-5xl tracking-wide">My clips</h1>
          <p className="mt-1 text-sm text-muted">Every finished clip from all your sessions, newest first.</p>
        </div>
        {clips && clips.length > 4 && (
          <label className="relative w-64">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-dim" />
            <input
              className="input pl-9"
              placeholder="Search clips"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              aria-label="Search clips"
            />
          </label>
        )}
      </div>

      {error && (
        <p className="rounded-lg border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad" role="alert">
          {error}
        </p>
      )}

      {clips === null && !error ? (
        <div className="flex justify-center py-24">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      ) : clips && clips.length === 0 ? (
        <div className="card px-6 py-12 text-center text-muted">
          No clips yet.{" "}
          <Link to="/" className="text-accent hover:underline">
            Upload a session
          </Link>{" "}
          and export your first highlight.
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {shown.map((c) => (
            <ExportCard
              key={c.id}
              clip={c}
              title={c.title}
              source={{ name: c.video_name, href: `/videos/${c.video_id}` }}
              onDelete={remove}
              onChange={update}
            />
          ))}
        </div>
      )}
    </div>
  );
}
