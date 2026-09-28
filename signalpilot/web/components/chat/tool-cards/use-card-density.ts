import { useCallback, useEffect, useState } from "react";
import type { RunStep } from "~/lib/chat-run-steps";

export type CardDensity = "running" | "compact" | "expanded";

export type CardDensityOptions = {
  step: RunStep;
  /** Truthy (or a fresh nonce) asks the card to open, e.g. a chip click. */
  focusRequested?: boolean | number;
};

export type CardDensityState = {
  density: CardDensity;
  /** Whether the card body is visible. */
  open: boolean;
  toggle: () => void;
  setOpen: (open: boolean) => void;
};

/**
 * Density policy for one tool card: collapsed unless the user asks.
 *
 * A card mounts as its one-line row whether it is running, done or failed,
 * and keeps that height through every status change. Only a click on the
 * row, or a focus request (a chip click in the group header), opens the
 * body. Nothing opens or closes on its own, so the transcript never grows
 * and shrinks as tools start and finish.
 *
 * `density` is "running" while the step runs and closed, "expanded" when
 * open, and "compact" otherwise.
 */
export function useCardDensity({
  step,
  focusRequested,
}: CardDensityOptions): CardDensityState {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (focusRequested) setOpen(true);
  }, [focusRequested]);

  const toggle = useCallback(() => setOpen((value) => !value), []);
  const density: CardDensity = open
    ? "expanded"
    : step.status === "running"
      ? "running"
      : "compact";
  return { density, open, toggle, setOpen };
}
