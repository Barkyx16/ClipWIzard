import { useState } from "react";
import { Loader2, RefreshCw } from "lucide-react";

import { AnalyzeSettings, api, Video } from "../api";

export default function RescanPanel({ video, onDone }: { video: Video; onDone: (v: Video) => void }) {
  const [settings, setSettings] = useState<AnalyzeSettings>(video.settings);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      onDone(await api.reanalyze(video.id, settings));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Re-scan failed");
    } finally {
      setBusy(false);
    }
  };
  return (
    <details className="relative">
      <summary className="btn-ghost cursor-pointer list-none">
        <RefreshCw className="h-4 w-4" /> Re-scan
      </summary>
      <div className="card absolute left-0 z-20 mt-2 w-72 space-y-3 p-4 shadow-2xl sm:left-auto sm:right-0">
        <label className="block">
          <span className="label">Clip length</span>
          <select
            className="input mt-1"
            value={settings.length}
            onChange={(e) => setSettings((s) => ({ ...s, length: e.target.value as AnalyzeSettings["length"] }))}
          >
            <option value="short">Short (12–30s)</option>
            <option value="medium">Medium (25–60s)</option>
            <option value="long">Long (45–90s)</option>
          </select>
        </label>
        <label className="block">
          <span className="label flex justify-between">
            Max clips <span className="text-ink">{settings.max_clips}</span>
          </span>
          <input
            type="range"
            min={1}
            max={30}
            value={settings.max_clips}
            onChange={(e) => setSettings((s) => ({ ...s, max_clips: Number(e.target.value) }))}
            className="mt-2 w-full"
          />
        </label>
        <label className="block">
          <span className="label">Sensitivity</span>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={settings.sensitivity}
            onChange={(e) => setSettings((s) => ({ ...s, sensitivity: Number(e.target.value) }))}
            className="mt-2 w-full"
          />
        </label>
        {error && <p className="text-xs text-bad">{error}</p>}
        <button type="button" className="btn-primary w-full" disabled={busy} onClick={run}>
          {busy && <Loader2 className="h-4 w-4 animate-spin" />} Scan again
        </button>
        <p className="text-[11px] text-dim">Exported clips are kept. Highlight edits will be replaced.</p>
      </div>
    </details>
  );
}
