"use client";

/** Legend / layer filter overlay (fixed order — identity, never cycled). */

import React from "react";

import { LAYER_COLOR, LAYER_LABEL, LAYER_ORDER, type MapLayer } from "./palette";
import type { ParsedMap } from "./parse-map";

export function LayerLegend({
  parsed,
  visibleLayers,
  onToggle,
}: {
  parsed: ParsedMap;
  visibleLayers: Set<MapLayer>;
  onToggle: (layer: MapLayer) => void;
}) {
  return (
    <div className="absolute bottom-3 left-3 rounded-[10px] border border-[var(--color-border)] bg-[var(--color-bg-card)]/90 p-2 backdrop-blur">
      {LAYER_ORDER.map((layer) => {
        const count = parsed.layerCounts[layer];
        if (count === 0) return null;
        const on = visibleLayers.has(layer);
        return (
          <button
            key={layer}
            type="button"
            onClick={() => onToggle(layer)}
            className={`flex w-full items-center gap-2 rounded px-1.5 py-[3px] text-left text-[10px] transition-opacity ${on ? "" : "opacity-35"} hover:bg-[var(--color-bg-hover)]`}
            aria-pressed={on}
          >
            <span className="h-2 w-2 rounded-[3px]" style={{ background: LAYER_COLOR[layer] }} aria-hidden="true" />
            <span className="text-[var(--color-text-muted)]">{LAYER_LABEL[layer]}</span>
            <span className="ml-auto font-mono text-[9px] text-[var(--color-text-dim)]">{count}</span>
          </button>
        );
      })}
      <div className="mt-1 border-t border-[var(--color-border)] px-1.5 pt-1 font-mono text-[9px] text-[var(--color-text-dim)]">
        {parsed.models.size} nodes · {parsed.edges.length} edges
      </div>
    </div>
  );
}
