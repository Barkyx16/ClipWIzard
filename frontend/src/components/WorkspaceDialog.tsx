import { useEffect, useRef, useState } from "react";
import { Check, Copy, Eye, EyeOff, KeyRound, Loader2, X } from "lucide-react";

import { api } from "../api";

export default function WorkspaceDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const [key, setKey] = useState<string | null>(null);
  const [reveal, setReveal] = useState(false);
  const [copied, setCopied] = useState(false);
  const [other, setOther] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) {
      d.showModal();
      setError(null);
      setOther("");
      api
        .workspace()
        .then((w) => setKey(w.key))
        .catch(() => setKey(null));
    } else if (!open && d.open) {
      d.close();
    }
  }, [open]);

  const copy = async () => {
    if (!key) return;
    await navigator.clipboard.writeText(key).catch(() => undefined);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const switchTo = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.switchWorkspace(other.trim());
      window.location.href = "/";
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not open that workspace");
      setBusy(false);
    }
  };

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onClick={(e) => e.target === ref.current && onClose()}
      className="m-auto w-[min(92vw,30rem)] rounded-2xl border border-line bg-surface p-0 text-ink backdrop:bg-black/70"
    >
      <div className="space-y-5 p-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="flex items-center gap-2 text-lg font-semibold">
              <KeyRound className="h-5 w-5 text-accent" /> Your workspace
            </h2>
            <p className="mt-1 text-sm text-muted">
              Your uploads and clips are private to this browser. Use this key to open them on another device. Anyone
              with the key can see your clips, so keep it to yourself.
            </p>
          </div>
          <button type="button" className="btn-icon shrink-0" aria-label="Close" onClick={onClose}>
            <X className="h-4 w-4" />
          </button>
        </div>

        <div>
          <p className="label mb-1.5">Workspace key</p>
          <div className="flex gap-2">
            <input
              readOnly
              className="input font-mono text-xs"
              type={reveal ? "text" : "password"}
              value={key ?? ""}
              aria-label="Workspace key"
            />
            <button
              type="button"
              className="btn-icon shrink-0"
              aria-label={reveal ? "Hide key" : "Show key"}
              onClick={() => setReveal((r) => !r)}
            >
              {reveal ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
            <button type="button" className="btn-icon shrink-0" aria-label="Copy key" onClick={copy} disabled={!key}>
              {copied ? <Check className="h-4 w-4 text-good" /> : <Copy className="h-4 w-4" />}
            </button>
          </div>
        </div>

        <div className="border-t border-line pt-5">
          <p className="label mb-1.5">Open a different workspace</p>
          <div className="flex gap-2">
            <input
              className="input font-mono text-xs"
              placeholder="Paste a workspace key"
              value={other}
              onChange={(e) => setOther(e.target.value)}
              aria-label="Workspace key to open"
            />
            <button
              type="button"
              className="btn-ghost shrink-0"
              disabled={other.trim().length < 32 || busy}
              onClick={switchTo}
            >
              {busy && <Loader2 className="h-4 w-4 animate-spin" />} Open
            </button>
          </div>
          <p className="mt-2 text-xs text-dim">Copy your current key first if you want to come back to it.</p>
          {error && <p className="mt-2 text-sm text-bad">{error}</p>}
        </div>
      </div>
    </dialog>
  );
}
