import {
  ArrowDownIcon,
  ArrowUpIcon,
  CheckCircle2Icon,
  ChevronDownIcon,
  ChevronRightIcon,
  ColumnsIcon,
  CopyIcon,
  FileCodeIcon,
  ShieldCheckIcon,
  TagIcon,
  XCircleIcon,
  XIcon,
} from "lucide-react";
import React, { useState } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/utils/cn";
import { copyToClipboard } from "@/utils/copy";
import { LAYER_LABELS, LAYER_THEMES } from "./layer-colors";
import type { DbtLineageData, DbtLineageNode } from "./types";

interface Props {
  node: DbtLineageNode;
  data: DbtLineageData;
  onClose: () => void;
  onNavigate: (nodeId: string) => void;
}

export const ModelDetailPanel: React.FC<Props> = ({
  node,
  data,
  onClose,
  onNavigate,
}) => {
  const theme = LAYER_THEMES[node.layer];

  return (
    <div className="flex flex-col h-full bg-zinc-950/95 border-l border-zinc-800 w-[320px] overflow-hidden">
      {/* Header */}
      <div className={cn("px-4 py-3 border-b border-zinc-800", theme.headerBg)}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 min-w-0">
            <span
              className={cn(
                "shrink-0 w-5 h-5 flex items-center justify-center rounded text-[10px] font-bold",
                theme.badge,
                theme.badgeText,
              )}
            >
              {node.materialization.charAt(0).toUpperCase()}
            </span>
            <h3
              className={cn("font-bold text-sm truncate", theme.headerText)}
              title={node.name}
            >
              {node.name}
            </h3>
          </div>
          <Button
            variant="text"
            size="xs"
            onClick={onClose}
            className="shrink-0"
          >
            <XIcon className="w-4 h-4 text-zinc-400" />
          </Button>
        </div>
        <div className="flex items-center gap-2 mt-1.5">
          <span
            className={cn(
              "text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded",
              theme.badge,
              theme.badgeText,
            )}
          >
            {LAYER_LABELS[node.layer]}
          </span>
          <span className="text-[10px] text-zinc-500 font-mono">
            {node.schema}.{node.name}
          </span>
        </div>
      </div>

      {/* Scrollable body */}
      <div className="flex-1 overflow-y-auto">
        {/* Description */}
        {node.description && (
          <Section title="Description">
            <p className="text-xs text-zinc-300 leading-relaxed">
              {node.description}
            </p>
          </Section>
        )}

        {/* Columns */}
        {node.columns.length > 0 && (
          <Section title="Columns" icon={<ColumnsIcon className="w-3 h-3" />} count={node.columnCount}>
            <div className="space-y-0.5">
              {node.columns.map((col) => (
                <div
                  key={col.name}
                  className="flex items-start gap-2 px-2 py-1 rounded hover:bg-zinc-800/50 group"
                >
                  <code className="text-[11px] font-mono text-zinc-200 shrink-0">
                    {col.name}
                  </code>
                  {col.data_type && (
                    <span className="text-[10px] text-zinc-500 font-mono shrink-0">
                      {col.data_type}
                    </span>
                  )}
                  {col.description && (
                    <span className="text-[10px] text-zinc-500 truncate ml-auto">
                      {col.description}
                    </span>
                  )}
                </div>
              ))}
            </div>
          </Section>
        )}

        {/* Tests */}
        {node.tests.length > 0 && (
          <Section
            title="Tests"
            icon={<ShieldCheckIcon className="w-3 h-3" />}
            count={node.testCount}
          >
            <div className="space-y-0.5">
              {node.tests.map((test) => (
                <div
                  key={test.name}
                  className="flex items-center gap-2 px-2 py-1 rounded hover:bg-zinc-800/50"
                >
                  {test.status === "pass" || test.status === "success" ? (
                    <CheckCircle2Icon className="w-3 h-3 text-green-400 shrink-0" />
                  ) : test.status === "fail" || test.status === "error" ? (
                    <XCircleIcon className="w-3 h-3 text-red-400 shrink-0" />
                  ) : (
                    <span className="w-3 h-3 rounded-full bg-zinc-700 shrink-0" />
                  )}
                  <span className="text-[11px] text-zinc-300 truncate">
                    {test.type}
                  </span>
                  {test.column && (
                    <code className="text-[10px] text-zinc-500 font-mono ml-auto">
                      {test.column}
                    </code>
                  )}
                </div>
              ))}
            </div>
          </Section>
        )}

        {/* Dependencies */}
        <Section
          title="Upstream"
          icon={<ArrowUpIcon className="w-3 h-3" />}
          count={node.parents.length}
        >
          {node.parents.length === 0 ? (
            <p className="text-[10px] text-zinc-600 italic px-2">
              No upstream dependencies
            </p>
          ) : (
            <div className="space-y-0.5">
              {node.parents.map((parentId) => {
                const parent = data.nodes.get(parentId);
                if (!parent) {return null;}
                const pt = LAYER_THEMES[parent.layer];
                return (
                  <button
                    key={parentId}
                    type="button"
                    className="w-full flex items-center gap-2 px-2 py-1 rounded hover:bg-zinc-800/50 cursor-pointer text-left"
                    onClick={() => onNavigate(parentId)}
                  >
                    <span
                      className={cn(
                        "w-4 h-4 flex items-center justify-center rounded text-[8px] font-bold shrink-0",
                        pt.badge,
                        pt.badgeText,
                      )}
                    >
                      {parent.materialization.charAt(0).toUpperCase()}
                    </span>
                    <span className={cn("text-[11px] truncate", pt.accent)}>
                      {parent.name}
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </Section>

        <Section
          title="Downstream"
          icon={<ArrowDownIcon className="w-3 h-3" />}
          count={node.children.length}
        >
          {node.children.length === 0 ? (
            <p className="text-[10px] text-zinc-600 italic px-2">
              No downstream dependents
            </p>
          ) : (
            <div className="space-y-0.5">
              {node.children.map((childId) => {
                const child = data.nodes.get(childId);
                if (!child) {return null;}
                const ct = LAYER_THEMES[child.layer];
                return (
                  <button
                    key={childId}
                    type="button"
                    className="w-full flex items-center gap-2 px-2 py-1 rounded hover:bg-zinc-800/50 cursor-pointer text-left"
                    onClick={() => onNavigate(childId)}
                  >
                    <span
                      className={cn(
                        "w-4 h-4 flex items-center justify-center rounded text-[8px] font-bold shrink-0",
                        ct.badge,
                        ct.badgeText,
                      )}
                    >
                      {child.materialization.charAt(0).toUpperCase()}
                    </span>
                    <span className={cn("text-[11px] truncate", ct.accent)}>
                      {child.name}
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </Section>

        {/* Tags */}
        {node.tags.length > 0 && (
          <Section title="Tags" icon={<TagIcon className="w-3 h-3" />}>
            <div className="flex flex-wrap gap-1 px-2">
              {node.tags.map((tag) => (
                <span
                  key={tag}
                  className="text-[10px] bg-zinc-800 text-zinc-400 px-1.5 py-0.5 rounded"
                >
                  {tag}
                </span>
              ))}
            </div>
          </Section>
        )}

        {/* Raw SQL */}
        {node.rawCode && (
          <Section title="SQL" icon={<FileCodeIcon className="w-3 h-3" />}>
            <div className="relative group">
              <pre className="text-[10px] font-mono text-zinc-300 bg-zinc-900/80 rounded p-2 max-h-[300px] overflow-auto whitespace-pre-wrap leading-relaxed">
                {node.rawCode}
              </pre>
              <Button
                variant="text"
                size="xs"
                className="absolute top-1 right-1 opacity-0 group-hover:opacity-100 transition-opacity"
                onClick={() => copyToClipboard(node.rawCode || "")}
              >
                <CopyIcon className="w-3 h-3" />
              </Button>
            </div>
          </Section>
        )}

        {/* Metadata */}
        <Section title="Info">
          <div className="space-y-1 px-2">
            <MetaRow label="Path" value={node.path} />
            <MetaRow label="Schema" value={`${node.database}.${node.schema}`} />
            <MetaRow label="Materialization" value={node.materialization} />
            {node.runTime != null && (
              <MetaRow
                label="Last run"
                value={
                  node.runTime < 1
                    ? `${(node.runTime * 1000).toFixed(0)}ms`
                    : `${node.runTime.toFixed(2)}s`
                }
              />
            )}
          </div>
        </Section>
      </div>
    </div>
  );
};

// ── Helpers ─────────────────────────────────────────────────────

const Section: React.FC<{
  title: string;
  icon?: React.ReactNode;
  count?: number;
  children: React.ReactNode;
}> = ({ title, icon, count, children }) => {
  const [open, setOpen] = useState(true);
  return (
    <div className="border-b border-zinc-800/50">
      <button
        type="button"
        className="w-full flex items-center gap-1.5 px-4 py-2 text-[10px] font-bold uppercase tracking-wider text-zinc-500 hover:text-zinc-300 transition-colors cursor-pointer"
        onClick={() => setOpen(!open)}
      >
        {open ? (
          <ChevronDownIcon className="w-3 h-3" />
        ) : (
          <ChevronRightIcon className="w-3 h-3" />
        )}
        {icon}
        {title}
        {count != null && (
          <span className="text-zinc-600 font-normal ml-1">({count})</span>
        )}
      </button>
      {open && <div className="px-2 pb-3">{children}</div>}
    </div>
  );
};

const MetaRow: React.FC<{ label: string; value: string }> = ({
  label,
  value,
}) => (
  <div className="flex items-center justify-between">
    <span className="text-[10px] text-zinc-500">{label}</span>
    <span className="text-[10px] text-zinc-300 font-mono truncate ml-4 max-w-[180px]">
      {value}
    </span>
  </div>
);
