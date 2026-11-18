import { useEffect, useRef } from "react";

/** Calls `fn` every `ms` while `active` is true. Latest `fn` is always used. */
export function usePolling(fn: () => void | Promise<void>, ms: number, active: boolean) {
  const saved = useRef(fn);
  saved.current = fn;
  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    let timer: number | undefined;
    const tick = async () => {
      try {
        await saved.current();
      } finally {
        if (!cancelled) timer = window.setTimeout(tick, ms);
      }
    };
    timer = window.setTimeout(tick, ms);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [ms, active]);
}
