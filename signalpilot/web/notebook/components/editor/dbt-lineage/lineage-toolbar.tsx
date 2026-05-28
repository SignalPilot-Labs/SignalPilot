import {
  ArrowDownIcon,
  ArrowRightIcon,
  RefreshCwIcon,
  SearchIcon,
} from "lucide-react";
import React from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/utils/cn";
import { LAYER_LABELS, LAYER_THEMES } from "./layer-colors";
import type { DbtModelLayer, LayoutDirection, LineageFilterState } from "./types";

const ALL_LAYERS: DbtModelLayer[] = [
  "seed",
  "staging",
  "intermediate",
  "dimension",
  "fact",
  "mart",
  "other",
];

interface Props {
  filter: LineageFilterState;
  onToggleLayer: (layer: DbtModelLayer) => void;
  onSetSearch: (query: string) => void;
  layoutDirection: LayoutDirection;
  onSetDirection: (dir: LayoutDirection) => void;
  onReload: () => void;
  loading: boolean;
  nodeCount: number;
  edgeCount: number;
}

export const LineageToolbar: React.FC<Props> = ({
  filter,
  onToggleLayer,
  onSetSearch,
  layoutDirection,
  onSetDirection,
  onReload,
  loading,
  nodeCount,
  edgeCount,
}) => {
  return (
    <div className="flex items-center gap-2 px-3 py-2 border-b border-zinc-800 bg-zinc-950/80 flex-wrap">
      {/* Search */}
      <div className="relative">
        <SearchIcon className="absolute left-2 top-1/2 -translate-y-1/2 w-3 h-3 text-zinc-500" />
        <input
          type="text"
          className="text-[11px] font-mono bg-zinc-900 rounded pl-7 pr-2 py-1 border border-zinc-800 focus:outline-none focus:ring-1 focus:ring-zinc-600 w-[160px] text-zinc-300 placeholder:text-zinc-600"
          placeholder="Search models..."
          value={filter.searchQuery}
          onChange={(e) => onSetSearch(e.target.value)}
        />
      </div>

      {/* Separator */}
      <div className="h-4 border-l border-zinc-800" />

      {/* Layer toggles */}
      <div className="flex items-center gap-1">
        {ALL_LAYERS.map((layer) => {
          const theme = LAYER_THEMES[layer];
          const active = filter.layers.has(layer);
          return (
            <button
              key={layer}
              type="button"
              onClick={() => onToggleLayer(layer)}
              className={cn(
                "text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded transition-all cursor-pointer",
                active
                  ? `${theme.badge} ${theme.badgeText}`
                  : "bg-zinc-900 text-zinc-600",
              )}
              title={`${active ? "Hide" : "Show"} ${LAYER_LABELS[layer]} layer`}
            >
              {LAYER_LABELS[layer]}
            </button>
          );
        })}
      </div>

      {/* Separator */}
      <div className="h-4 border-l border-zinc-800" />

      {/* Layout direction */}
      <div className="flex items-center gap-0.5 bg-zinc-900 rounded border border-zinc-800">
        <button
          type="button"
          className={cn(
            "p-1 rounded-l transition-colors cursor-pointer",
            layoutDirection === "LR"
              ? "bg-zinc-700 text-zinc-200"
              : "text-zinc-500 hover:text-zinc-300",
          )}
          onClick={() => onSetDirection("LR")}
          title="Horizontal layout"
        >
          <ArrowRightIcon className="w-3 h-3" />
        </button>
        <button
          type="button"
          className={cn(
            "p-1 rounded-r transition-colors cursor-pointer",
            layoutDirection === "TB"
              ? "bg-zinc-700 text-zinc-200"
              : "text-zinc-500 hover:text-zinc-300",
          )}
          onClick={() => onSetDirection("TB")}
          title="Vertical layout"
        >
          <ArrowDownIcon className="w-3 h-3" />
        </button>
      </div>

      {/* Reload */}
      <Button
        variant="outline"
        size="xs"
        className="h-6 px-2 text-[10px] bg-zinc-900 border-zinc-800 text-zinc-400 hover:text-zinc-200"
        onClick={onReload}
        disabled={loading}
      >
        <RefreshCwIcon
          className={cn("w-3 h-3 mr-1", loading && "animate-spin")}
        />
        Reload
      </Button>

      {/* Stats */}
      <div className="ml-auto flex items-center gap-2 text-[10px] text-zinc-600">
        <span>{nodeCount} models</span>
        <span>{edgeCount} edges</span>
      </div>
    </div>
  );
};
