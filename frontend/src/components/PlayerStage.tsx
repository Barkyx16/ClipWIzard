import { forwardRef, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";

import { Aspect, Rect, Timeline, Video } from "../api";

interface Props {
  video: Video;
  aspect: Aspect;
  cropX: number;
  currentTime: number;
  timeline: Timeline | null;
  drawing: boolean;
  onTimeUpdate: () => void;
  onFacecamDrawn: (rect: Rect) => void;
  onCancelDrawing: () => void;
}

const OUT_W = 1080;
const OUT_H = 1920;

/** Interpolated smart-crop centre (0..1) at time t. */
export function smartCentre(timeline: Timeline | null, t: number): number {
  const path = timeline?.crop_path;
  const hop = timeline?.crop_hop;
  if (!path?.length || !hop) return 0.5;
  const pos = Math.min(Math.max(t / hop, 0), path.length - 1);
  const i = Math.floor(pos);
  const j = Math.min(i + 1, path.length - 1);
  return path[i] + (path[j] - path[i]) * (pos - i);
}

/** Horizontal crop window (fractions of the frame) for the vertical formats. */
function cropWindow(
  video: Video,
  aspect: Aspect,
  cropX: number,
  centre: number,
): { left: number; width: number } | null {
  const srcAspect = video.width / video.height;
  let target = 9 / 16;
  if (aspect === "vertical_facecam") {
    const fc = video.layout?.facecam;
    if (!fc) return null;
    const fw = fc.w * video.width;
    const fh = fc.h * video.height;
    const top = Math.min(Math.max((OUT_W * fh) / fw, OUT_H * 0.25), OUT_H * 0.45);
    target = OUT_W / (OUT_H - top);
  } else if (aspect !== "vertical_crop" && aspect !== "vertical_smart") {
    return null;
  }
  if (srcAspect <= target) return null;
  const width = target / srcAspect;
  const c = aspect === "vertical_crop" ? null : centre;
  const left = c === null ? (1 - width) * cropX : Math.min(Math.max(c - width / 2, 0), 1 - width);
  return { left, width };
}

const PlayerStage = forwardRef<HTMLVideoElement, Props>(function PlayerStage(
  { video, aspect, cropX, currentTime, timeline, drawing, onTimeUpdate, onFacecamDrawn, onCancelDrawing },
  videoRef,
) {
  const boxRef = useRef<HTMLDivElement>(null);
  const start = useRef<{ x: number; y: number } | null>(null);
  const [draft, setDraft] = useState<Rect | null>(null);

  const crop = cropWindow(video, aspect, cropX, smartCentre(timeline, currentTime));
  const facecam = video.layout?.facecam;

  const point = (e: ReactPointerEvent) => {
    const r = boxRef.current!.getBoundingClientRect();
    return {
      x: Math.min(Math.max((e.clientX - r.left) / r.width, 0), 1),
      y: Math.min(Math.max((e.clientY - r.top) / r.height, 0), 1),
    };
  };
  const rectFrom = (a: { x: number; y: number }, b: { x: number; y: number }): Rect => ({
    x: Math.min(a.x, b.x),
    y: Math.min(a.y, b.y),
    w: Math.abs(a.x - b.x),
    h: Math.abs(a.y - b.y),
  });

  const pct = (v: number) => `${(v * 100).toFixed(3)}%`;

  return (
    <div
      ref={boxRef}
      className="relative mx-auto max-h-[62vh] overflow-hidden rounded-xl bg-black"
      style={{ aspectRatio: `${video.width} / ${video.height}` }}
    >
      <video
        ref={videoRef}
        src={video.source_url}
        controls={!drawing}
        playsInline
        preload="metadata"
        className="absolute inset-0 h-full w-full"
        onTimeUpdate={onTimeUpdate}
        onSeeked={onTimeUpdate}
      />

      {crop && !drawing && (
        <div className="pointer-events-none absolute inset-0 [&>div]:transition-all [&>div]:duration-300 [&>div]:ease-linear">
          <div className="absolute inset-y-0 left-0 bg-black/60" style={{ width: pct(crop.left) }} />
          <div
            className="absolute inset-y-0 border-2 border-accent"
            style={{ left: pct(crop.left), width: pct(crop.width) }}
          />
          <div className="absolute inset-y-0 right-0 bg-black/60" style={{ width: pct(1 - crop.left - crop.width) }} />
        </div>
      )}

      {facecam && aspect === "vertical_facecam" && !drawing && (
        <div
          className="pointer-events-none absolute border-2 border-dashed border-primary bg-primary/10"
          style={{ left: pct(facecam.x), top: pct(facecam.y), width: pct(facecam.w), height: pct(facecam.h) }}
        >
          <span className="absolute left-1 top-1 rounded bg-primary px-1 text-[10px] font-bold text-on-primary">
            CAM
          </span>
        </div>
      )}

      {drawing && (
        <div
          className="absolute inset-0 cursor-crosshair touch-none bg-black/30"
          onPointerDown={(e) => {
            e.currentTarget.setPointerCapture(e.pointerId);
            start.current = point(e);
            setDraft({ ...start.current, w: 0, h: 0 });
          }}
          onPointerMove={(e) => start.current && setDraft(rectFrom(start.current, point(e)))}
          onPointerUp={(e) => {
            if (!start.current) return;
            const r = rectFrom(start.current, point(e));
            start.current = null;
            setDraft(null);
            if (r.w > 0.03 && r.h > 0.03) onFacecamDrawn(r);
          }}
          onKeyDown={(e) => e.key === "Escape" && onCancelDrawing()}
          tabIndex={0}
          role="application"
          aria-label="Drag a box around your facecam"
        >
          <p className="pointer-events-none absolute inset-x-0 top-3 mx-auto w-fit rounded-lg bg-black/80 px-3 py-1.5 text-sm font-semibold">
            Drag a box around your facecam
          </p>
          {draft && (
            <div
              className="pointer-events-none absolute border-2 border-primary bg-primary/20"
              style={{ left: pct(draft.x), top: pct(draft.y), width: pct(draft.w), height: pct(draft.h) }}
            />
          )}
        </div>
      )}
    </div>
  );
});

export default PlayerStage;
