import { useEffect, useState } from "react";
import {
  BookmarkPlus,
  Captions,
  Check,
  Copy,
  Crosshair,
  Loader2,
  Minus,
  Plus,
  ScanFace,
  Scissors,
  Trash2,
  X,
} from "lucide-react";

import { Aspect, Highlight } from "../api";
import { formatTime, parseTime } from "../lib/format";

export interface EditorState {
  start: number;
  end: number;
  aspect: Aspect;
  cropX: number;
  titleOverlay: boolean;
  title: string;
  captions: boolean;
  watermark: string;
}

const ASPECTS: { value: Aspect; label: string; hint: string; w: number; h: number; tip: string }[] = [
  {
    value: "vertical_blur",
    label: "Blur fill",
    hint: "9:16",
    w: 9,
    h: 16,
    tip: "Whole frame over a blurred background",
  },
  {
    value: "vertical_smart",
    label: "Smart",
    hint: "9:16",
    w: 9,
    h: 16,
    tip: "Full-screen crop that pans to follow the action",
  },
  {
    value: "vertical_facecam",
    label: "Facecam",
    hint: "9:16",
    w: 9,
    h: 16,
    tip: "Your facecam stacked above the gameplay",
  },
  {
    value: "vertical_crop",
    label: "Fixed",
    hint: "9:16",
    w: 9,
    h: 16,
    tip: "Full-screen crop at a position you choose",
  },
  { value: "square", label: "Square", hint: "1:1", w: 1, h: 1, tip: "1:1 with blurred background" },
  { value: "landscape", label: "Original", hint: "16:9", w: 16, h: 9, tip: "Keep the original shape" },
];

function TimeField({
  label,
  value,
  onChange,
  onUsePlayhead,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  onUsePlayhead: () => void;
}) {
  const [text, setText] = useState(formatTime(value, true));
  useEffect(() => setText(formatTime(value, true)), [value]);
  const commit = () => {
    const parsed = parseTime(text);
    if (parsed === null) setText(formatTime(value, true));
    else onChange(parsed);
  };
  return (
    <div>
      <span className="label">{label}</span>
      <div className="mt-1.5 flex items-center gap-1">
        <button
          type="button"
          className="btn-icon h-9 w-8"
          aria-label={`${label} minus 1 second`}
          onClick={() => onChange(value - 1)}
        >
          <Minus className="h-3.5 w-3.5" />
        </button>
        <input
          className="input text-center font-mono"
          value={text}
          aria-label={label}
          onChange={(e) => setText(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => e.key === "Enter" && commit()}
        />
        <button
          type="button"
          className="btn-icon h-9 w-8"
          aria-label={`${label} plus 1 second`}
          onClick={() => onChange(value + 1)}
        >
          <Plus className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          className="btn-icon h-9 w-9"
          title="Set to playhead"
          aria-label={`Set ${label} to playhead`}
          onClick={onUsePlayhead}
        >
          <Crosshair className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

function Sparkle() {
  return (
    <svg viewBox="0 0 12 12" className="-ml-1 -mt-5 h-3 w-3 fill-accent" aria-hidden>
      <path d="M6 0l1.4 4.6L12 6 7.4 7.4 6 12 4.6 7.4 0 6l4.6-1.4z" />
    </svg>
  );
}

function SignalBar({ label, value, color }: { label: string; value: number | undefined; color: string }) {
  const pct = Math.round(Math.min(1, Math.max(0, value ?? 0)) * 100);
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-14 text-muted">{label}</span>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-bg">
        <div className="h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: color }} />
      </div>
    </div>
  );
}

function CopyButton({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      className="btn-icon h-8 w-8"
      aria-label="Copy to clipboard"
      onClick={async () => {
        await navigator.clipboard.writeText(text).catch(() => undefined);
        setDone(true);
        setTimeout(() => setDone(false), 1500);
      }}
    >
      {done ? <Check className="h-4 w-4 text-good" /> : <Copy className="h-4 w-4" />}
    </button>
  );
}

interface Props {
  captionsAvailable: boolean;
  hasFacecam: boolean;
  drawingFacecam: boolean;
  onMarkFacecam: () => void;
  onClearFacecam: () => void;
  highlight: Highlight | null;
  state: EditorState;
  duration: number;
  currentTime: number;
  exporting: boolean;
  onChange: (patch: Partial<EditorState>) => void;
  onExport: () => void;
  onSaveHighlight: () => void;
  onDeleteHighlight: () => void;
}

export default function ClipEditor({
  highlight,
  state,
  duration,
  currentTime,
  exporting,
  captionsAvailable,
  hasFacecam,
  drawingFacecam,
  onMarkFacecam,
  onClearFacecam,
  onChange,
  onExport,
  onSaveHighlight,
  onDeleteHighlight,
}: Props) {
  const clamp = (t: number) => Math.min(Math.max(0, t), duration);
  const length = state.end - state.start;
  const invalid = length < 1 || length > 180;
  const edited =
    !highlight || Math.abs(highlight.start - state.start) > 0.05 || Math.abs(highlight.end - state.end) > 0.05;
  const social = highlight
    ? [highlight.caption, highlight.hashtags.map((t) => `#${t}`).join(" ")].filter(Boolean).join("\n\n")
    : "";

  return (
    <section className="card space-y-5 p-5" aria-label="Clip editor">
      <div className="flex items-center justify-between">
        <h3 className="font-display text-2xl tracking-wide">Edit clip</h3>
        <span className={`text-sm ${invalid ? "text-bad" : "text-muted"}`}>
          {length.toFixed(1)}s {invalid && (length < 1 ? "· too short" : "· max 180s")}
        </span>
      </div>

      {highlight?.description && <p className="text-sm text-muted">{highlight.description}</p>}

      <div className="-mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {edited && !invalid && (
          <button
            type="button"
            className="inline-flex items-center gap-1 text-accent hover:underline"
            onClick={onSaveHighlight}
          >
            <BookmarkPlus className="h-3.5 w-3.5" /> Save range as a highlight
          </button>
        )}
        {highlight && (
          <button
            type="button"
            className="inline-flex items-center gap-1 text-muted hover:text-bad"
            onClick={onDeleteHighlight}
          >
            <Trash2 className="h-3.5 w-3.5" /> Remove this highlight
          </button>
        )}
      </div>

      {highlight && (
        <div className="space-y-1.5 rounded-xl border border-line bg-surface-2/60 p-3">
          <p className="label mb-1">Why this moment</p>
          <SignalBar label="Audio" value={highlight.signals.audio} color="var(--color-primary)" />
          <SignalBar label="Gunfire" value={highlight.signals.gunfire} color="var(--color-bad)" />
          <SignalBar label="Motion" value={highlight.signals.motion} color="var(--color-accent)" />
          {highlight.signals.ai_hype !== undefined && (
            <SignalBar label="AI hype" value={highlight.signals.ai_hype / 100} color="var(--color-primary-2)" />
          )}
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        <TimeField
          label="Start"
          value={state.start}
          onChange={(v) => onChange({ start: clamp(v) })}
          onUsePlayhead={() => onChange({ start: clamp(currentTime) })}
        />
        <TimeField
          label="End"
          value={state.end}
          onChange={(v) => onChange({ end: clamp(v) })}
          onUsePlayhead={() => onChange({ end: clamp(currentTime) })}
        />
      </div>

      <div>
        <p className="label mb-2">Format</p>
        <div className="grid grid-cols-3 gap-1.5">
          {ASPECTS.map((a) => (
            <button
              key={a.value}
              type="button"
              title={a.tip}
              onClick={() => onChange({ aspect: a.value })}
              aria-pressed={state.aspect === a.value}
              className={`flex flex-col items-center gap-1.5 rounded-xl border px-1 py-2 text-xs transition ${
                state.aspect === a.value
                  ? "border-primary bg-primary/10 text-ink"
                  : "border-line text-muted hover:border-muted/60"
              }`}
            >
              <span className="flex h-9 items-center">
                <span
                  className={`block rounded-sm border-2 ${state.aspect === a.value ? "border-primary" : "border-dim"}`}
                  style={{ width: (a.w / Math.max(a.w, a.h)) * 32, height: (a.h / Math.max(a.w, a.h)) * 32 }}
                >
                  {a.value === "vertical_facecam" && (
                    <span
                      className={`block h-1/3 border-b-2 ${state.aspect === a.value ? "border-primary" : "border-dim"}`}
                    />
                  )}
                </span>
                {a.value === "vertical_smart" && <Sparkle />}
              </span>
              <span className="font-semibold">{a.label}</span>
              <span className="-mt-1 text-[10px] opacity-75">{a.hint}</span>
            </button>
          ))}
        </div>
        {state.aspect === "vertical_facecam" && (
          <div className="mt-3 flex flex-wrap items-center gap-2 rounded-xl border border-line bg-surface-2/60 p-3 text-sm">
            <span className={`flex-1 ${hasFacecam ? "text-muted" : "text-warn"}`}>
              {drawingFacecam
                ? "Drag a box around your facecam on the video."
                : hasFacecam
                  ? "Facecam marked. It goes on top, gameplay below."
                  : "Mark where your facecam is on the video first."}
            </span>
            <button type="button" className="btn-ghost px-3 py-1.5 text-xs" onClick={onMarkFacecam}>
              <ScanFace className="h-4 w-4" /> {drawingFacecam ? "Cancel" : hasFacecam ? "Redraw" : "Mark facecam"}
            </button>
            {hasFacecam && !drawingFacecam && (
              <button type="button" className="btn-icon h-8 w-8" aria-label="Remove facecam" onClick={onClearFacecam}>
                <X className="h-4 w-4" />
              </button>
            )}
          </div>
        )}
        {state.aspect === "vertical_smart" && (
          <p className="mt-2 text-xs text-muted">
            The crop pans to follow the action. Press play to preview the moving frame on the player.
          </p>
        )}
        {state.aspect === "vertical_crop" && (
          <label className="mt-3 block">
            <span className="label">Crop position</span>
            <input
              type="range"
              min={0}
              max={1}
              step={0.01}
              value={state.cropX}
              onChange={(e) => onChange({ cropX: Number(e.target.value) })}
              className="mt-2 w-full"
            />
          </label>
        )}
      </div>

      <label className={`flex items-start gap-2 text-sm ${captionsAvailable ? "" : "opacity-60"}`}>
        <input
          type="checkbox"
          className="mt-0.5 h-4 w-4 accent-primary"
          checked={state.captions && captionsAvailable}
          disabled={!captionsAvailable}
          onChange={(e) => onChange({ captions: e.target.checked })}
        />
        <span>
          <span className="flex items-center gap-1.5">
            <Captions className="h-4 w-4 text-accent" /> Auto captions
          </span>
          <span className="block text-xs text-muted">
            {captionsAvailable
              ? "Word-by-word subtitles from the voice chat and commentary."
              : "Install faster-whisper on the server to turn this on."}
          </span>
        </span>
      </label>

      <div className="space-y-2">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            className="h-4 w-4 accent-primary"
            checked={state.titleOverlay}
            onChange={(e) => onChange({ titleOverlay: e.target.checked })}
          />
          Burn title into the video
        </label>
        <input
          className="input"
          value={state.title}
          maxLength={120}
          placeholder="Clip title"
          onChange={(e) => onChange({ title: e.target.value })}
          aria-label="Clip title"
        />
      </div>

      <label className="block">
        <span className="label">Your handle</span>
        <input
          className="input mt-1.5"
          value={state.watermark}
          maxLength={40}
          placeholder="@yourchannel (optional watermark)"
          onChange={(e) => onChange({ watermark: e.target.value })}
        />
      </label>

      {social && (
        <div className="rounded-xl border border-line bg-surface-2/60 p-3">
          <div className="mb-1 flex items-center justify-between">
            <p className="label">Post caption</p>
            <CopyButton text={social} />
          </div>
          <p className="whitespace-pre-wrap text-sm text-muted">{social}</p>
        </div>
      )}

      <button
        type="button"
        className="btn-primary w-full py-3"
        disabled={invalid || exporting || (state.aspect === "vertical_facecam" && !hasFacecam)}
        onClick={onExport}
      >
        {exporting ? <Loader2 className="h-5 w-5 animate-spin" /> : <Scissors className="h-5 w-5" />}
        Export clip
      </button>
    </section>
  );
}
