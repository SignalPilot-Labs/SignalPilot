"use client";

import { useEffect, useRef, type RefObject } from "react";

/**
 * Keeps the transcript's last visible line in place while the composer dock
 * (plan list, approval card) changes height. The dock is sticky at the
 * bottom of the scroll viewport, so growing it would otherwise cover the
 * lines directly above it. Every height delta is added to `scrollTop`, so
 * the line that sat above the dock still sits above it after the change.
 * Returns the ref to attach to the dock element.
 */
export function useDockScrollCompensation(
  viewportRef: RefObject<HTMLElement | null>,
): RefObject<HTMLDivElement | null> {
  const dockRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const dock = dockRef.current;
    if (!dock || typeof ResizeObserver === "undefined") return;
    let lastHeight = dock.getBoundingClientRect().height;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[entries.length - 1];
      const height = entry?.contentRect.height ?? lastHeight;
      const delta = height - lastHeight;
      lastHeight = height;
      const viewport = viewportRef.current;
      if (!viewport || delta === 0) return;
      viewport.scrollTop += delta;
    });
    observer.observe(dock);
    return () => observer.disconnect();
  }, [viewportRef]);
  return dockRef;
}
