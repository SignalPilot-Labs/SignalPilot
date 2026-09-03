"use client";

/**
 * The inspector's left-edge grab strip. Pointer capture keeps the drag on
 * the handle (the ReactFlow pane next to it never sees the moves), width
 * updates are rAF-throttled, text selection is off while dragging, and a
 * double-click resets. As a keyboard separator: arrows resize by a step
 * (Shift for a big one), Home and End snap to the bounds.
 */

import React, { useCallback, useEffect, useRef, useState } from "react";

import { keyboardResize, type WidthBounds } from "./inspector-resize";

export function InspectorResizeHandle({
  width,
  bounds,
  onPreview,
  onCommit,
  onReset,
}: {
  width: number;
  bounds: WidthBounds;
  onPreview: (px: number) => void;
  onCommit: (px: number) => void;
  onReset: () => void;
}) {
  const [dragging, setDragging] = useState(false);
  const drag = useRef<{ startX: number; startWidth: number; latest: number; raf: number | null } | null>(null);

  const clamp = useCallback(
    (px: number) => Math.min(bounds.max, Math.max(bounds.min, Math.round(px))),
    [bounds],
  );

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0 && e.pointerType === "mouse") return;
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { startX: e.clientX, startWidth: width, latest: width, raf: null };
    setDragging(true);
  };

  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d) return;
    // The handle sits on the left edge: moving left widens.
    d.latest = clamp(d.startWidth + (d.startX - e.clientX));
    if (d.raf !== null) return;
    d.raf = requestAnimationFrame(() => {
      d.raf = null;
      onPreview(d.latest);
    });
  };

  const endDrag = (e: React.PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d) return;
    drag.current = null;
    if (d.raf !== null) cancelAnimationFrame(d.raf);
    if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId);
    setDragging(false);
    onCommit(d.latest);
  };

  // No text selection under the pointer while the width follows it.
  useEffect(() => {
    if (!dragging) return;
    const body = document.body;
    const prevSelect = body.style.userSelect;
    const prevCursor = body.style.cursor;
    body.style.userSelect = "none";
    body.style.cursor = "col-resize";
    return () => {
      body.style.userSelect = prevSelect;
      body.style.cursor = prevCursor;
    };
  }, [dragging]);

  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const next = keyboardResize(e.key, e.shiftKey, width, bounds);
    if (next === null) return;
    e.preventDefault();
    if (next !== width) onCommit(next);
  };

  const max = Number.isFinite(bounds.max) ? bounds.max : undefined;
  return (
    <div
      role="separator"
      tabIndex={0}
      aria-orientation="vertical"
      aria-label="Resize inspector"
      aria-valuenow={width}
      aria-valuemin={bounds.min}
      aria-valuemax={max}
      data-testid="inspector-resize-handle"
      data-dragging={dragging ? "1" : "0"}
      title="Drag to resize. Double-click to reset."
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onDoubleClick={onReset}
      onKeyDown={onKeyDown}
      className="group absolute inset-y-0 left-[-4px] z-20 w-2 cursor-col-resize touch-none select-none outline-none"
    >
      {/* The visible affordance: a thin bar that lights on hover, drag, focus. */}
      <div
        aria-hidden="true"
        className={`mx-auto h-full w-[3px] rounded-full transition-colors ${
          dragging
            ? "bg-[var(--color-accent)]"
            : "bg-transparent group-hover:bg-[var(--color-border-hover)] group-focus-visible:bg-[var(--color-accent)]"
        }`}
      />
    </div>
  );
}
