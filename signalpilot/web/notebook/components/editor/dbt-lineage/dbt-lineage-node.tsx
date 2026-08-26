import {
  CheckCircle2Icon,
  ColumnsIcon,
  ShieldCheckIcon,
  XCircleIcon,
} from "lucide-react";
import React, { memo } from "react";
import { Handle, Position, type NodeProps } from "reactflow";
import { cn } from "@/utils/cn";
import {
  LAYER_LABELS,
  LAYER_THEMES,
  MATERIALIZATION_ICONS,
} from "./layer-colors";
import type { DbtLineageNode } from "./types";

export interface DbtNodeData {
  node: DbtLineageNode;
  layoutDirection: "TB" | "LR";
}

const DbtLineageNodeComponent: React.FC<NodeProps<DbtNodeData>> = ({
  data,
  selected,
}) => {
  const { node, layoutDirection } = data;
  const theme = LAYER_THEMES[node.layer];
  const matIcon = MATERIALIZATION_ICONS[node.materialization] ?? "?";
  const isHorizontal = layoutDirection === "LR";

  const passingTests = node.tests.filter(
    (t) => t.status === "pass" || t.status === "success",
  ).length;
  const failingTests = node.tests.filter(
    (t) => t.status === "fail" || t.status === "error",
  ).length;
  const totalTests = node.testCount;

  return (
    <>
      <Handle
        type="target"
        id="target"
        position={isHorizontal ? Position.Left : Position.Top}
        className="!w-2 !h-2 !border-2 !bg-zinc-800 !border-zinc-500"
      />

      <div
        className={cn(
          "rounded-lg border overflow-hidden transition-all duration-200 min-w-[200px] max-w-[280px]",
          theme.bg,
          theme.border,
          selected
            ? `ring-2 ring-white/30 shadow-lg ${theme.glow}`
            : "shadow-md shadow-black/20",
        )}
      >
        {/* Header */}
        <div
          className={cn(
            "flex items-center gap-2 px-3 py-2",
            theme.headerBg,
          )}
        >
          {/* Materialization badge */}
          <span
            className={cn(
              "flex items-center justify-center w-5 h-5 rounded text-[10px] font-bold shrink-0",
              theme.badge,
              theme.badgeText,
            )}
            title={node.materialization}
          >
            {matIcon}
          </span>

          {/* Model name */}
          <span
            className={cn(
              "font-semibold text-xs truncate flex-1",
              theme.headerText,
            )}
            title={node.name}
          >
            {node.name}
          </span>

          {/* Run status */}
          {node.runStatus && (
            <span className="shrink-0">
              {node.runStatus === "success" || node.runStatus === "pass" ? (
                <CheckCircle2Icon className="w-3.5 h-3.5 text-green-400" />
              ) : (
                <XCircleIcon className="w-3.5 h-3.5 text-red-400" />
              )}
            </span>
          )}
        </div>

        {/* Body */}
        <div className="px-3 py-2 space-y-1.5">
          {/* Layer badge */}
          <div className="flex items-center gap-1.5">
            <span
              className={cn(
                "text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded",
                theme.badge,
                theme.badgeText,
              )}
            >
              {LAYER_LABELS[node.layer]}
            </span>
            {node.materialization !== "unknown" && (
              <span className="text-[9px] text-zinc-500 font-mono">
                {node.materialization}
              </span>
            )}
          </div>

          {/* Description (truncated) */}
          {node.description && (
            <p className="text-[10px] text-zinc-400 line-clamp-2 leading-tight">
              {node.description}
            </p>
          )}

          {/* Stats row */}
          <div className="flex items-center gap-3 pt-0.5">
            {node.columnCount > 0 && (
              <span className="flex items-center gap-1 text-[10px] text-zinc-400">
                <ColumnsIcon className="w-3 h-3" />
                {node.columnCount}
              </span>
            )}
            {totalTests > 0 && (
              <span className="flex items-center gap-1 text-[10px] text-zinc-400">
                <ShieldCheckIcon className="w-3 h-3" />
                <span>
                  {passingTests > 0 && (
                    <span className="text-green-400">{passingTests}</span>
                  )}
                  {failingTests > 0 && (
                    <>
                      {passingTests > 0 && "/"}
                      <span className="text-red-400">{failingTests}</span>
                    </>
                  )}
                  {passingTests === 0 && failingTests === 0 && totalTests}
                </span>
              </span>
            )}
            {node.runTime != null && (
              <span className="text-[10px] text-zinc-500 ml-auto font-mono">
                {node.runTime < 1
                  ? `${(node.runTime * 1000).toFixed(0)}ms`
                  : `${node.runTime.toFixed(1)}s`}
              </span>
            )}
          </div>
        </div>
      </div>

      <Handle
        type="source"
        id="source"
        position={isHorizontal ? Position.Right : Position.Bottom}
        className="!w-2 !h-2 !border-2 !bg-zinc-800 !border-zinc-500"
      />
    </>
  );
};

export const DbtLineageNodeMemo = memo(DbtLineageNodeComponent);
DbtLineageNodeMemo.displayName = "DbtLineageNode";

export const dbtNodeTypes = {
  dbtModel: DbtLineageNodeMemo,
};
