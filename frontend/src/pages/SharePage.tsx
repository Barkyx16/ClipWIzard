import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Check, Copy, Download, Loader2 } from "lucide-react";

import { api, SharedClip } from "../api";

export default function SharePage() {
  const { token = "" } = useParams();
  const [clip, setClip] = useState<SharedClip | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const meta = document.createElement("meta");
    meta.name = "robots";
    meta.content = "noindex";
    document.head.appendChild(meta);
    api
      .shared(token)
      .then((c) => {
        setClip(c);
        document.title = `${c.title} · ClipWizard`;
      })
      .catch((e) => setError(e instanceof Error ? e.message : "This link doesn't work"));
    return () => meta.remove();
  }, [token]);

  const post = clip ? [clip.caption, clip.hashtags.map((t) => `#${t}`).join(" ")].filter(Boolean).join("\n\n") : "";
  const vertical = clip?.aspect?.startsWith("vertical");

  return (
    <div className="flex min-h-screen flex-col items-center px-4 py-8">
      <Link to="/" className="mb-6 flex items-center gap-2.5">
        <img src="/favicon.svg" alt="" className="h-7 w-7" />
        <span className="font-display text-2xl leading-none tracking-wide">
          Clip<span className="text-gradient">Wizard</span>
        </span>
      </Link>

      {error ? (
        <div className="card max-w-md p-8 text-center">
          <p className="font-semibold">{error}</p>
          <p className="mt-2 text-sm text-muted">The owner may have turned this link off.</p>
        </div>
      ) : !clip ? (
        <Loader2 className="mt-24 h-8 w-8 animate-spin text-primary" />
      ) : (
        <div className={`card w-full overflow-hidden ${vertical ? "max-w-sm" : "max-w-3xl"}`}>
          <video
            src={clip.video_url}
            controls
            playsInline
            autoPlay
            muted
            loop
            className={`w-full bg-black ${vertical ? "aspect-[9/16]" : "aspect-video"}`}
          />
          <div className="space-y-4 p-4">
            <h1 className="text-lg font-semibold leading-snug">{clip.title}</h1>
            <a href={clip.download_url} className="btn-primary w-full py-3" download>
              <Download className="h-5 w-5" /> Download clip
            </a>
            {post && (
              <div className="rounded-xl border border-line bg-surface-2/60 p-3">
                <div className="mb-1 flex items-center justify-between">
                  <p className="label">Caption</p>
                  <button
                    type="button"
                    className="btn-icon h-8 w-8"
                    aria-label="Copy caption"
                    onClick={async () => {
                      await navigator.clipboard.writeText(post).catch(() => undefined);
                      setCopied(true);
                      setTimeout(() => setCopied(false), 1500);
                    }}
                  >
                    {copied ? <Check className="h-4 w-4 text-good" /> : <Copy className="h-4 w-4" />}
                  </button>
                </div>
                <p className="whitespace-pre-wrap text-sm text-muted">{post}</p>
              </div>
            )}
            <p className="text-center text-xs text-dim">
              Clipped with{" "}
              <Link to="/" className="underline hover:text-ink">
                ClipWizard
              </Link>
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
