"use client";

/**
 * The left panel collapsed to a slim rail. Shown when a wide inspector
 * would squeeze the canvas under its reserve; the button hands the width
 * back so the full panel fits again.
 */

import { PanelLeftOpen } from "lucide-react";
import React from "react";

import { LEFT_RAIL_WIDTH } from "./inspector-resize";

export function PanelRail({ label, onExpand }: { label: string; onExpand: () => void }) {
  return (
    <div
      data-testid="lineage-panel-rail"
      style={{ width: LEFT_RAIL_WIDTH }}
      className="flex h-full shrink-0 flex-col items-center gap-2 border-r border-[var(--color-border)] bg-[var(--color-bg-card)]/60 py-2"
    >
      <button
        type="button"
        onClick={onExpand}
        aria-label={`Show ${label} panel`}
        title={`Show ${label} panel`}
        className="flex h-7 w-7 items-center justify-center rounded-[7px] text-[var(--color-text-dim)] transition-colors hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
      >
        <PanelLeftOpen className="h-3.5 w-3.5" />
      </button>
      <span
        aria-hidden="true"
        style={{ writingMode: "vertical-rl" }}
        className="mt-1 text-[9px] uppercase tracking-[0.14em] text-[var(--color-text-dim)]"
      >
        {label}
      </span>
    </div>
  );
}
