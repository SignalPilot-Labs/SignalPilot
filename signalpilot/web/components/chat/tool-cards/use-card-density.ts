import { useCallback, useEffect, useRef, useState } from "react";
import type { RunStep } from "~/lib/chat-run-steps";
import type { ToolCardDefinition } from "./registry";

export type CardDensity = "running" | "compact" | "expanded";

/** How long a just-completed card stays expanded before folding to a chip. */
export const COMPLETION_HOLD_MS = 900;

export type CardDensityOptions = {
  step: RunStep;
  def: ToolCardDefinition;
  isLastInGroup: boolean;
  /** The enclosing activity group is still the live trailing chain. */
  groupLive: boolean;
  /** Truthy (or a fresh nonce) asks the card to open, e.g. a chip click. */
  focusRequested?: boolean | number;
};

export type CardDensityState = {
  density: CardDensity;
  /** Whether the frame body is visible (running cards can be folded by hand). */
  open: boolean;
  toggle: () => void;
  setOpen: (open: boolean) => void;
};

/**
 * Density policy for one tool card.
 *
 * - running → "running"; a step that re-enters running clears the user's
 *   toggle so a retry opens again.
 * - running → completed: hold "expanded" for COMPLETION_HOLD_MS (the
 *   check-pop lands), then "compact" unless the user opened it, the step
 *   failed (errors stay open), or the definition pins it open while the
 *   group is live.
 * - mounted already complete (replay, seek, reopened group): "compact"
 *   immediately with no timers, so `?at=` frames stay deterministic. The
 *   same exceptions apply.
 */
export function useCardDensity({
  step,
  def,
  isLastInGroup,
  groupLive,
  focusRequested,
}: CardDensityOptions): CardDensityState {
  const running = step.status === "running";
  const failed = step.status === "failed";
  const [userOpen, setUserOpen] = useState<boolean | null>(null);
  const [holding, setHolding] = useState(false);
  const wasRunning = useRef(running);

  useEffect(() => {
    if (running) {
      wasRunning.current = true;
      setUserOpen(null);
      setHolding(false);
      return;
    }
    // Mounted complete: no hold, no timer.
    if (!wasRunning.current) return;
    wasRunning.current = false;
    setHolding(true);
    const timer = window.setTimeout(() => setHolding(false), COMPLETION_HOLD_MS);
    return () => window.clearTimeout(timer);
  }, [running]);

  useEffect(() => {
    if (focusRequested) setUserOpen(true);
  }, [focusRequested]);

  const pinned =
    failed ||
    holding ||
    (groupLive && (def.stayOpenOnComplete?.(step, isLastInGroup) ?? false));
  const open = userOpen ?? (running || pinned);
  const density: CardDensity = running ? "running" : open ? "expanded" : "compact";

  const toggle = useCallback(() => setUserOpen((value) => !(value ?? (running || pinned))), [
    running,
    pinned,
  ]);
  const setOpen = useCallback((value: boolean) => setUserOpen(value), []);

  return { density, open, toggle, setOpen };
}
