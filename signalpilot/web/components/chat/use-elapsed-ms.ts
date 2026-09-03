import { useEffect, useState } from "react";

/** Live boots tick from the event timestamp; replays and skewed clocks
 * (baseline negative or implausibly old) fall back to time-since-mount. */
export function useElapsedMs(startedAt: string, active: boolean): number {
  const [anchor] = useState(() => {
    const parsed = Date.parse(startedAt);
    const age = Date.now() - parsed;
    return Number.isFinite(parsed) && age >= 0 && age < 30 * 60_000
      ? parsed
      : Date.now();
  });
  const [elapsed, setElapsed] = useState(() => Math.max(0, Date.now() - anchor));
  useEffect(() => {
    if (!active) return;
    const tick = () => setElapsed(Math.max(0, Date.now() - anchor));
    tick();
    const interval = window.setInterval(tick, 100);
    return () => window.clearInterval(interval);
  }, [anchor, active]);
  return elapsed;
}
