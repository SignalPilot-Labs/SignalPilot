"use client";

/**
 * Owns the inspector width for one lineage surface. The preference (a raw
 * px value, or null for "use the default") lives in state and, on commit,
 * in localStorage under one key shared by the page and the modal. The
 * rendered width is that preference clamped to the measured container, so
 * a stored wide value on a small viewport still leaves the canvas visible.
 */

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type RefObject } from "react";

import {
  clampWidth,
  defaultInspectorWidth,
  isWide,
  readStoredWidth,
  wideInspectorWidth,
  widthBounds,
  writeStoredWidth,
  type InspectorSurface,
  type WidthBounds,
} from "./inspector-resize";

export interface InspectorWidthState {
  /** Rendered width (clamped). */
  width: number;
  bounds: WidthBounds;
  containerWidth: number;
  wide: boolean;
  /** Live update during a drag: state only. */
  preview: (px: number) => void;
  /** Update and persist. */
  commit: (px: number) => void;
  /** Back to the surface default; clears the stored preference. */
  reset: () => void;
  /** Toggle between the wide preset and the width before it. */
  toggleWide: () => void;
}

const useIsoLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;

export function useInspectorWidth(
  containerRef: RefObject<HTMLElement | null>,
  surface: InspectorSurface,
  /** Full width of the left panel, so the default keeps it open. */
  leftPanelWidth = 0,
): InspectorWidthState {
  const [preferred, setPreferred] = useState<number | null>(null);
  const [containerWidth, setContainerWidth] = useState(0);
  const beforeWideRef = useRef<number | null>(null);

  // Hydrate the preference after mount: SSR has no storage.
  useEffect(() => {
    setPreferred(readStoredWidth(typeof window === "undefined" ? null : window.localStorage));
  }, []);

  // Track the container so the bounds follow the viewport.
  useIsoLayoutEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const measure = () => setContainerWidth(el.clientWidth);
    measure();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", measure);
      return () => window.removeEventListener("resize", measure);
    }
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [containerRef]);

  const bounds = useMemo(() => widthBounds(containerWidth), [containerWidth]);
  const fallback = defaultInspectorWidth(surface, containerWidth, leftPanelWidth);
  const width = clampWidth(preferred ?? fallback, bounds);

  const preview = useCallback((px: number) => setPreferred(px), []);
  const commit = useCallback((px: number) => {
    const next = Math.round(px);
    setPreferred(next);
    writeStoredWidth(window.localStorage, next);
  }, []);
  const reset = useCallback(() => {
    beforeWideRef.current = null;
    setPreferred(null);
    writeStoredWidth(window.localStorage, null);
  }, []);
  const toggleWide = useCallback(() => {
    if (isWide(width, containerWidth)) {
      commit(beforeWideRef.current ?? fallback);
      beforeWideRef.current = null;
      return;
    }
    beforeWideRef.current = width;
    commit(wideInspectorWidth(containerWidth));
  }, [width, containerWidth, fallback, commit]);

  return {
    width,
    bounds,
    containerWidth,
    wide: isWide(width, containerWidth),
    preview,
    commit,
    reset,
    toggleWide,
  };
}
