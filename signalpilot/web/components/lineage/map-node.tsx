"use client";

/**
 * dbt map node card. Follows dbt's lineage card anatomy (accent edge, name,
 * materialization, resource meta) restyled for the SignalPilot dark theme.
 * Identity channels: layer accent + layer label + materialization glyph —
 * never color alone. Sources are visually distinct (dashed, pill corners),
 * mirroring dbt's source/model distinction.
 */

import React, { memo } from "react";
import { Handle, Position, type NodeProps } from "reactflow";

import { LAYER_COLOR, LAYER_LABEL, matGlyph } from "./palette";
import type { MapModel } from "./parse-map";

export interface MapNodeData {
  model: MapModel;
  /** null = nothing focused; true = on the focused lineage path; false = dimmed */
  onPath: boolean | null;
  selected: boolean;
}

export const NODE_W = 232;
export const NODE_H = 68;

function MapNodeInner({ data }: NodeProps<MapNodeData>) {
  const { model, onPath, selected } = data;
  const color = LAYER_COLOR[model.layer];
  const dimmed = onPath === false;
  const isSource = model.layer === "source";
  const failableTests = model.tests.length;

  return (
    <div
      className="group relative transition-opacity duration-150"
      style={{
        width: NODE_W,
        height: NODE_H,
        opacity: dimmed ? 0.14 : 1,
      }}
    >
      <Handle type="target" position={Position.Left} className="!w-1.5 !h-1.5 !border-0" style={{ background: color, opacity: dimmed ? 0 : 0.9 }} />
      <div
        className="h-full w-full overflow-hidden bg-[var(--color-bg-card)] transition-shadow duration-150"
        style={{
          borderRadius: isSource ? 999 : 10,
          border: `1px ${isSource ? "dashed" : "solid"} ${
            selected ? color : onPath ? `${color}88` : "var(--color-border)"
          }`,
          boxShadow: selected
            ? `0 0 0 1px ${color}, 0 4px 24px ${color}33`
            : onPath
              ? `0 2px 12px ${color}22`
              : "none",
        }}
      >
        <div className="flex h-full items-stretch">
          {/* Layer accent — the primary color channel */}
          {!isSource && (
            <div className="w-[3px] shrink-0" style={{ background: color }} />
          )}
          <div className={`flex min-w-0 flex-1 flex-col justify-center gap-1 py-2 ${isSource ? "px-4" : "px-2.5"}`}>
            <div className="flex items-center gap-1.5">
              <span
                className="flex h-4 w-4 shrink-0 items-center justify-center rounded text-[10px] leading-none"
                style={{ color, background: `${color}1f` }}
                aria-hidden="true"
              >
                {matGlyph(model.materialized, model.layer)}
              </span>
              <span className="truncate font-mono text-[11px] font-semibold leading-none text-[var(--color-text)]">
                {model.name}
              </span>
            </div>
            <div className="flex items-center gap-1.5 pl-[22px] text-[9px] leading-none text-[var(--color-text-dim)]">
              <span className="uppercase tracking-[0.08em]" style={{ color: dimmed ? undefined : `${color}dd` }}>
                {LAYER_LABEL[model.layer]}
              </span>
              <span aria-hidden="true">·</span>
              <span className="truncate">{model.schema || model.materialized}</span>
              {model.columns.length > 0 && (
                <>
                  <span aria-hidden="true">·</span>
                  <span>{model.columns.length} col</span>
                </>
              )}
            </div>
          </div>
          {failableTests > 0 && (
            <div className="flex items-center pr-2" title={`${failableTests} test${failableTests === 1 ? "" : "s"}`}>
              <span className="rounded-[5px] border border-[var(--color-border)] px-1 py-0.5 text-[9px] leading-none text-[var(--color-text-muted)]">
                ✓{failableTests}
              </span>
            </div>
          )}
        </div>
      </div>
      <Handle type="source" position={Position.Right} className="!w-1.5 !h-1.5 !border-0" style={{ background: color, opacity: dimmed ? 0 : 0.9 }} />
    </div>
  );
}

export const MapNode = memo(MapNodeInner);
export const mapNodeTypes = { dbtMap: MapNode };
