import { useEffect, useState } from "react";
import { prefersReducedMotion } from "~/components/chat/tool-cards/card-primitives";

/** Gap between two items entering the live transcript. */
export const REVEAL_INTERVAL_MS = 90;
/** A backlog longer than this skips ahead so the view never lags far behind. */
export const MAX_REVEAL_BACKLOG = 6;

/**
 * How many of `total` items to show, pacing new ones in one at a time.
 *
 * Several tool calls often arrive in one event batch; mounting them in the
 * same frame reads as a jolt. While `live`, each new item waits
 * REVEAL_INTERVAL_MS after the previous one. Everything present at mount
 * shows at once, and a non-live list (history, replay seek, `?at=` frames)
 * or reduced motion always shows everything, so replay frames stay
 * deterministic.
 */
export function useRevealCount(total: number, live: boolean): number {
  const [shown, setShown] = useState(total);
  const paced = live && !prefersReducedMotion();

  useEffect(() => {
    if (!paced || shown >= total) {
      if (shown !== total && (!paced || shown > total)) setShown(total);
      return;
    }
    if (total - shown > MAX_REVEAL_BACKLOG) {
      setShown(total - MAX_REVEAL_BACKLOG);
      return;
    }
    const timer = window.setTimeout(
      () => setShown((value) => Math.min(total, value + 1)),
      REVEAL_INTERVAL_MS,
    );
    return () => window.clearTimeout(timer);
  }, [paced, shown, total]);

  return paced ? Math.min(shown, total) : total;
}
