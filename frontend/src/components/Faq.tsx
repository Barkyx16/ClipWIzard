import { ChevronDown } from "lucide-react";

import { Health } from "../api";
import { formatBytes } from "../lib/format";

export default function Faq({ health }: { health: Health | null }) {
  const limit = health ? formatBytes(health.max_upload_mb * 1024 * 1024) : "8 GB";
  const days = health?.retention_days ?? 0;
  const items: { q: string; a: string }[] = [
    {
      q: "Is my footage private?",
      a:
        "Yes. Each browser gets its own private workspace, and nobody else can see your uploads or clips unless you " +
        "create a share link for a clip. Use the Workspace button to open the same workspace on another device." +
        (days ? ` Sessions are deleted automatically after ${days} days without activity.` : ""),
    },
    {
      q: "What can I upload?",
      a:
        `MP4, MOV, MKV, WebM and other common video files up to ${limit}, including full stream VODs. ` +
        "Big uploads resume automatically if your connection drops. You can also paste a link from " +
        (health?.import_sites?.length ? health.import_sites.join(", ") : "YouTube, Twitch, Kick or Medal") +
        ".",
    },
    {
      q: "How does it find the best moments?",
      a:
        "It listens and watches for spikes: gunfire-like bursts, explosions and crashes, yelling, and fast motion " +
        "like chases. Each moment is compared with the rest of your recording, so loud streams with music still work.",
    },
    {
      q: "What does the AI do?",
      a: health?.ai_enabled
        ? "Claude looks at a few frames from each highlight and writes a title, a caption and hashtags. It also " +
          "pushes menus, maps and loading screens down the list."
        : "When the server has an Anthropic API key, Claude names each highlight, writes captions and hashtags, and " +
          "filters out menus and loading screens. Detection works without it.",
    },
    {
      q: "Can it make clips without me editing anything?",
      a:
        "Yes. Tick Auto-export when you upload or paste a link and the best moments render on their own, in the " +
        "format you used last. You'll get a notification when they're ready, and every clip shows up in My clips.",
    },
    {
      q: "Which format should I pick?",
      a:
        "Blur fill keeps the whole frame and is the safe default. Smart crop fills the screen and pans to follow the " +
        "action. Facecam stacks your webcam above the gameplay, which works well for stream clips.",
    },
    {
      q: "Will my clips have a watermark?",
      a: "No ClipWizard watermark, ever. You can add your own channel handle if you want one.",
    },
    {
      q: "Can I post the clips anywhere?",
      a:
        "Only upload footage you have the rights to use, and follow each platform's rules and the game publisher's " +
        "content guidelines when you post.",
    },
  ];
  return (
    <section aria-labelledby="faq-heading" className="mx-auto max-w-3xl">
      <h2 id="faq-heading" className="mb-4 font-display text-4xl tracking-wide">
        Questions
      </h2>
      <div className="divide-y divide-line rounded-2xl border border-line bg-surface/60">
        {items.map((item) => (
          <details key={item.q} className="group px-5 py-4">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-4 font-semibold">
              {item.q}
              <ChevronDown className="h-4 w-4 shrink-0 text-muted transition group-open:rotate-180" />
            </summary>
            <p className="mt-2 text-sm leading-relaxed text-muted">{item.a}</p>
          </details>
        ))}
      </div>
    </section>
  );
}
