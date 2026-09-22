"use client";

/**
 * Width rules and state for the resizable chat artifacts panel. The numbers
 * are pure so they can be unit tested; the hook owns measurement, the
 * stored preference, and the clamping that keeps the transcript readable
 * when the viewport shrinks under a stored width.
 *
 * The lineage inspector has the same shape (inspector-resize.ts) but its
 * own bounds and key: the two surfaces are resized independently.
 */

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type RefObject,
} from "react";

/** localStorage key for the panel's remembered width. */
export const ARTIFACTS_WIDTH_KEY = "sp:chat-artifacts-width";

/** Narrowest panel that still shows a file usefully. */
export const ARTIFACTS_MIN_WIDTH = 360;
/** Transcript that must stay visible left of the panel. It stays
 * readable well under its max-w-3xl content column. */
export const TRANSCRIPT_RESERVE = 420;
/** Default share of the container, matching the old fixed 46%. */
export const DEFAULT_FRACTION = 0.46;
/** Keyboard steps (px). */
export const KEY_STEP = 32;
export const KEY_STEP_LARGE = 128;

export interface WidthBounds {
  min: number;
  max: number;
}

/**
 * Bounds for a container this wide. An unmeasured container (0) is
 * unbounded so the first paint does not snap to the minimum.
 */
export function widthBounds(containerWidth: number): WidthBounds {
  if (!(containerWidth > 0)) {
    return { min: ARTIFACTS_MIN_WIDTH, max: Number.POSITIVE_INFINITY };
  }
  const max = Math.max(
    ARTIFACTS_MIN_WIDTH,
    Math.floor(containerWidth - TRANSCRIPT_RESERVE),
  );
  return { min: ARTIFACTS_MIN_WIDTH, max };
}

export function clampWidth(width: number, bounds: WidthBounds): number {
  if (!Number.isFinite(width)) return bounds.min;
  return Math.min(bounds.max, Math.max(bounds.min, Math.round(width)));
}

/** Default width: a share of the container, inside the bounds. */
export function defaultArtifactsWidth(containerWidth: number): number {
  if (!(containerWidth > 0)) return ARTIFACTS_MIN_WIDTH;
  return clampWidth(containerWidth * DEFAULT_FRACTION, widthBounds(containerWidth));
}

/** Parse a stored preference; null for anything that is not a sane number. */
export function parseStoredWidth(raw: string | null | undefined): number | null {
  if (raw == null) return null;
  const value = Number(raw);
  if (!Number.isFinite(value) || value < ARTIFACTS_MIN_WIDTH) return null;
  return Math.round(value);
}

export function readStoredWidth(
  storage: Pick<Storage, "getItem"> | null | undefined,
): number | null {
  try {
    return parseStoredWidth(storage?.getItem(ARTIFACTS_WIDTH_KEY));
  } catch {
    return null;
  }
}

export function writeStoredWidth(
  storage: Pick<Storage, "setItem" | "removeItem"> | null | undefined,
  width: number | null,
): void {
  try {
    if (width === null) storage?.removeItem(ARTIFACTS_WIDTH_KEY);
    else storage?.setItem(ARTIFACTS_WIDTH_KEY, String(Math.round(width)));
  } catch {
    // Private mode or a full store: the width just does not persist.
  }
}

/** What a key press asks the separator to do. */
export type ResizeIntent =
  | { type: "delta"; px: number }
  | { type: "snap"; edge: "min" | "max" };

/**
 * Keyboard resize on the separator, as an intent rather than a width. The
 * hook applies it to the CURRENT width, so holding a key steps on every
 * repeat instead of recomputing from the width the last render captured.
 * The handle sits on the panel's left edge, so ArrowLeft widens and
 * ArrowRight narrows.
 */
export function resizeIntent(key: string, shift: boolean): ResizeIntent | null {
  const step = shift ? KEY_STEP_LARGE : KEY_STEP;
  switch (key) {
    case "ArrowLeft":
      return { type: "delta", px: step };
    case "ArrowRight":
      return { type: "delta", px: -step };
    case "Home":
      return { type: "snap", edge: "min" };
    case "End":
      return { type: "snap", edge: "max" };
    default:
      return null;
  }
}

/** The width an intent produces from `width`, inside `bounds`. */
export function applyResizeIntent(
  intent: ResizeIntent,
  width: number,
  bounds: WidthBounds,
): number {
  if (intent.type === "snap") {
    if (intent.edge === "min") return bounds.min;
    return Number.isFinite(bounds.max) ? bounds.max : clampWidth(width, bounds);
  }
  return clampWidth(width + intent.px, bounds);
}

export interface ArtifactsWidthState {
  /** Rendered width in px, already clamped to the container. */
  width: number;
  /**
   * True once the row has been measured. Before that the panel keeps its
   * CSS width: rendering a computed number against an unmeasured container
   * would paint one narrow frame, and the transcript's card density is
   * decided from the width it sees on mount.
   */
  measured: boolean;
  bounds: WidthBounds;
  /** Live update during a drag: state only, not persisted. */
  preview: (px: number) => void;
  /** Update and persist. */
  commit: (px: number) => void;
  /** Back to the default; clears the stored preference. */
  reset: () => void;
  /** Apply a keyboard intent to the current width and persist it. */
  nudge: (intent: ResizeIntent) => void;
}

const useIsoLayoutEffect =
  typeof window === "undefined" ? useEffect : useLayoutEffect;

/**
 * Width of the artifacts panel. `panelRef` is the panel itself; the row it
 * shares with the transcript is its parent, and that row's measured width
 * sets the bounds, so a stored wide value on a small window still leaves
 * the transcript visible.
 *
 * The row is read inside the layout effect rather than from a ref another
 * effect fills in: passive effects run after layout effects, so that order
 * would leave the panel unmeasured on mount in a production build (React's
 * development double-invoke hides it).
 */
export function useArtifactsWidth(
  panelRef: RefObject<HTMLElement | null>,
): ArtifactsWidthState {
  const [preferred, setPreferred] = useState<number | null>(null);
  const [containerWidth, setContainerWidth] = useState(0);
  // Skip the write on the hydrating read.
  const hydrated = useRef(false);

  useEffect(() => {
    setPreferred(
      readStoredWidth(typeof window === "undefined" ? null : window.localStorage),
    );
    hydrated.current = true;
  }, []);

  useIsoLayoutEffect(() => {
    // The panel is attached by the time layout effects run, so its parent
    // (the transcript + panel row) is available here.
    const row = panelRef.current?.parentElement ?? null;
    if (!row) return;
    const measure = () => setContainerWidth(row.clientWidth);
    measure();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", measure);
      return () => window.removeEventListener("resize", measure);
    }
    const observer = new ResizeObserver(measure);
    observer.observe(row);
    return () => observer.disconnect();
  }, [panelRef]);

  const bounds = useMemo(() => widthBounds(containerWidth), [containerWidth]);
  const width = clampWidth(
    preferred ?? defaultArtifactsWidth(containerWidth),
    bounds,
  );

  const preview = useCallback((px: number) => setPreferred(Math.round(px)), []);
  const commit = useCallback((px: number) => {
    const next = Math.round(px);
    setPreferred(next);
    if (hydrated.current) {
      writeStoredWidth(
        typeof window === "undefined" ? null : window.localStorage,
        next,
      );
    }
  }, []);
  // The updater reads the live width, so key repeat compounds instead of
  // recomputing from the width this render captured.
  const boundsRef = useRef(bounds);
  boundsRef.current = bounds;
  const fallbackRef = useRef(0);
  fallbackRef.current = defaultArtifactsWidth(containerWidth);
  const nudge = useCallback((intent: ResizeIntent) => {
    setPreferred((previous) => {
      const current = clampWidth(
        previous ?? fallbackRef.current,
        boundsRef.current,
      );
      const next = applyResizeIntent(intent, current, boundsRef.current);
      writeStoredWidth(
        typeof window === "undefined" ? null : window.localStorage,
        next,
      );
      return next;
    });
  }, []);
  const reset = useCallback(() => {
    setPreferred(null);
    writeStoredWidth(
      typeof window === "undefined" ? null : window.localStorage,
      null,
    );
  }, []);

  return {
    width,
    measured: containerWidth > 0,
    bounds,
    preview,
    commit,
    reset,
    nudge,
  };
}
