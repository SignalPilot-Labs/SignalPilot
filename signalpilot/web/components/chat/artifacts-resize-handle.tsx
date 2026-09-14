"use client";

/**
 * The artifacts panel's left-edge grab strip. Pointer capture keeps the
 * drag on the handle, width updates are rAF-throttled, text selection is
 * off while dragging, and a double-click resets to the default. As a
 * keyboard separator: arrows resize by a step (Shift for a big one), Home
 * and End snap to the bounds.
 */

import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  resizeIntent,
  type ResizeIntent,
  type WidthBounds,
} from "~/components/chat/artifacts-panel-width";

export function ArtifactsResizeHandle({
  width,
  bounds,
  onPreview,
  onCommit,
  onReset,
  onNudge,
}: {
  width: number;
  bounds: WidthBounds;
  onPreview: (px: number) => void;
  onCommit: (px: number) => void;
  onReset: () => void;
  onNudge: (intent: ResizeIntent) => void;
}) {
  const [dragging, setDragging] = useState(false);
  const drag = useRef<{
    startX: number;
    startWidth: number;
    latest: number;
    raf: number | null;
  } | null>(null);

  const clamp = useCallback(
    (px: number) => Math.min(bounds.max, Math.max(bounds.min, Math.round(px))),
    [bounds],
  );

  const onPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0 && event.pointerType === "mouse") return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = {
      startX: event.clientX,
      startWidth: width,
      latest: width,
      raf: null,
    };
    setDragging(true);
  };

  const onPointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    const state = drag.current;
    if (!state) return;
    // The handle sits on the left edge: moving left widens the panel.
    state.latest = clamp(state.startWidth + (state.startX - event.clientX));
    if (state.raf !== null) return;
    state.raf = requestAnimationFrame(() => {
      state.raf = null;
      onPreview(state.latest);
    });
  };

  const endDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    const state = drag.current;
    if (!state) return;
    drag.current = null;
    if (state.raf !== null) cancelAnimationFrame(state.raf);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    setDragging(false);
    onCommit(state.latest);
  };

  // No text selection under the pointer while the width follows it.
  useEffect(() => {
    if (!dragging) return;
    const body = document.body;
    const previousSelect = body.style.userSelect;
    const previousCursor = body.style.cursor;
    body.style.userSelect = "none";
    body.style.cursor = "col-resize";
    return () => {
      body.style.userSelect = previousSelect;
      body.style.cursor = previousCursor;
    };
  }, [dragging]);

  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const intent = resizeIntent(event.key, event.shiftKey);
    if (intent === null) return;
    event.preventDefault();
    onNudge(intent);
  };

  return (
    <div
      role="separator"
      tabIndex={0}
      aria-orientation="vertical"
      aria-label="Resize the artifacts panel"
      aria-valuenow={width}
      aria-valuemin={bounds.min}
      aria-valuemax={Number.isFinite(bounds.max) ? bounds.max : undefined}
      data-testid="artifacts-resize-handle"
      data-dragging={dragging ? "1" : "0"}
      title="Drag to resize. Double-click to reset."
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onDoubleClick={onReset}
      onKeyDown={onKeyDown}
      className="group absolute inset-y-0 left-[-4px] z-30 w-2 cursor-col-resize touch-none select-none outline-none"
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
