"use client";

import {
  AlertCircle,
  Bot,
  Check,
  FileCode2,
  FileDiff,
  FilePen,
  FileSearch,
  Globe,
  ListTodo,
  NotebookPen,
  Play,
  type LucideIcon,
} from "lucide-react";
import {
  formatCount,
  formatStepDuration,
  type RunStep,
  type RunStepCategory,
} from "~/lib/chat-run-steps";
import { resolveToolCard, type ToolCardAccent, type ToolCardDefinition } from "./registry";
import { NOUN_BY_KIND } from "./registry-tools";

/**
 * The compact density of a tool card: one pill with icon, title, stat and
 * outcome. `ToolChipStrip` lays a completed group's chips out in a row,
 * merging runs of the same successful kind ("3 queries · 2,410 rows").
 * The merge helpers are pure so they can be unit tested without React.
 */

/** Chips a strip shows before folding the rest into "+N more". */
export const MAX_STRIP_CHIPS = 6;

/**
 * Kind priority for the strip: the most decision-relevant work comes first
 * so the count cap never hides a query result behind a run of file reads.
 * Failed chips outrank everything; legacy/neutral merged chips come last.
 */
const KIND_PRIORITY = [
  "table",
  "table_list",
  "dbt_run",
  "schema",
  "column_profile",
  "validation",
  "terminal",
  "knowledge",
  "artifact",
  "json",
  "text",
] as const;

function chipRank(chip: ChipModel): number {
  if (!chip.ok) return -1;
  const index = KIND_PRIORITY.indexOf(chip.group as (typeof KIND_PRIORITY)[number]);
  return index === -1 ? KIND_PRIORITY.length : index;
}

/** Merged chips ordered by importance (stable within a rank). */
export function orderChips(chips: ChipModel[]): ChipModel[] {
  return chips
    .map((chip, index) => ({ chip, index, rank: chipRank(chip) }))
    .sort((a, b) => a.rank - b.rank || a.index - b.index)
    .map((entry) => entry.chip);
}

export type ChipModel = {
  key: string;
  /** Merge key: the card kind, or `cat:<category>` for legacy rows. */
  group: string;
  Icon: LucideIcon;
  accent: ToolCardAccent;
  title: string;
  stat: string | null;
  ok: boolean;
  /** Steps folded into this chip (1 for an unmerged chip). */
  stepKeys: string[];
  durationMs: number | null;
};

const CATEGORY_ICONS: Partial<Record<RunStepCategory, LucideIcon>> = {
  python: FileCode2,
  notebook: NotebookPen,
  "file-write": FilePen,
  "file-edit": FileDiff,
  "file-read": FileSearch,
  todo: ListTodo,
  web: Globe,
  subagent: Bot,
};

const CATEGORY_NOUNS: Partial<Record<RunStepCategory, string>> = {
  "file-write": "file",
  "file-edit": "edit",
  "file-read": "read",
  todo: "plan update",
  web: "web lookup",
  python: "code run",
  notebook: "notebook edit",
  subagent: "subagent",
  sql: "query",
  terminal: "command",
};

function plural(noun: string, count: number): string {
  if (count === 1) return noun;
  if (noun.endsWith("y")) return `${noun.slice(0, -1)}ies`;
  return `${noun}s`;
}

/** "1,204 rows · 312 ms" → { value: 1204, unit: "rows" }; null otherwise. */
export function parseStat(stat: string | null): { value: number; unit: string } | null {
  if (!stat) return null;
  const match = /^\s*([\d,]+(?:\.\d+)?)\s+([a-zA-Z]+)/.exec(stat);
  if (!match) return null;
  const value = Number(match[1].replace(/,/g, ""));
  if (!Number.isFinite(value)) return null;
  return { value, unit: match[2] };
}

/** A chip for one step, through its card definition or the legacy fallback. */
export function chipForStep(
  step: RunStep,
  def: ToolCardDefinition | null = resolveToolCard(step),
): ChipModel {
  const ok = step.status !== "failed";
  if (def) {
    const summary = def.summarize(step);
    return {
      key: step.key,
      group: def.kind,
      Icon: def.Icon,
      accent: def.accent,
      title: summary.title,
      stat: summary.stat,
      ok: ok && summary.ok,
      stepKeys: [step.key],
      durationMs: step.durationMs,
    };
  }
  return {
    key: step.key,
    group: `cat:${step.category}`,
    Icon: CATEGORY_ICONS[step.category] ?? Play,
    accent: "neutral",
    title: step.title,
    stat: step.file,
    ok,
    stepKeys: [step.key],
    durationMs: step.durationMs,
  };
}

function nounFor(group: string, sample: RunStep): string {
  if (group.startsWith("cat:")) {
    return CATEGORY_NOUNS[sample.category] ?? "step";
  }
  return NOUN_BY_KIND[group as keyof typeof NOUN_BY_KIND] ?? "tool call";
}

/**
 * Chips for a completed group: consecutive successful chips of one kind
 * merge into a count (stats summed when every member shares a unit);
 * failed chips never merge, so an error is always its own pill.
 */
export function mergeChips(
  steps: RunStep[],
  resolve: (step: RunStep) => ToolCardDefinition | null = resolveToolCard,
): ChipModel[] {
  const out: ChipModel[] = [];
  const members: RunStep[][] = [];
  for (const step of steps) {
    const chip = chipForStep(step, resolve(step));
    const last = out[out.length - 1];
    if (last && chip.ok && last.ok && last.group === chip.group) {
      last.stepKeys.push(step.key);
      members[members.length - 1].push(step);
      last.durationMs =
        last.durationMs == null || chip.durationMs == null
          ? null
          : last.durationMs + chip.durationMs;
      continue;
    }
    out.push(chip);
    members.push([step]);
  }
  return out.map((chip, index) => {
    const group = members[index];
    if (group.length === 1) return chip;
    const stats = group.map((step) => parseStat(chipForStep(step, resolve(step)).stat));
    const unit = stats[0]?.unit;
    const summable = unit !== undefined && stats.every((s) => s !== null && s.unit === unit);
    const total = summable ? stats.reduce((sum, s) => sum + (s?.value ?? 0), 0) : null;
    return {
      ...chip,
      title: `${group.length} ${plural(nounFor(chip.group, group[0]), group.length)}`,
      stat: total !== null && unit ? `${formatCount(total)} ${unit}` : null,
    };
  });
}

/** The pill itself; `flash` plays the pick highlight once. */
export function ChipPill({
  chip,
  onClick,
  flash = false,
  entering = false,
}: {
  chip: ChipModel;
  onClick?: () => void;
  flash?: boolean;
  entering?: boolean;
}) {
  const duration = formatStepDuration(chip.durationMs);
  const kind = chip.group.startsWith("cat:") ? "legacy" : chip.group;
  return (
    <button
      type="button"
      data-testid="chat-tool-chip"
      data-kind={kind}
      data-ok={chip.ok}
      data-accent={chip.accent}
      onClick={onClick}
      title={chip.stat ? `${chip.title} · ${chip.stat}` : chip.title}
      className={`inline-flex h-6 max-w-full items-center gap-1.5 rounded-full border bg-[var(--color-bg-input)] px-2 text-[11px] leading-none transition-colors hover:bg-[var(--color-bg-hover)] ${
        chip.ok
          ? "border-[var(--color-border)] text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
          : "border-[var(--color-error)]/35 text-[var(--color-error)]"
      } ${flash ? "chat-tool-chip-flash" : ""} ${entering ? "chat-tool-collapse-in" : ""}`}
    >
      <chip.Icon
        className={`h-3 w-3 flex-none ${chip.ok ? "chat-tool-accent-text" : ""}`}
      />
      <span className="truncate">{chip.title}</span>
      {chip.stat && (
        <>
          <span className="opacity-50">·</span>
          <span className="truncate font-mono text-[10.5px] tabular-nums">{chip.stat}</span>
        </>
      )}
      {chip.ok ? (
        <Check className="h-3 w-3 flex-none text-[var(--color-success)]/70" />
      ) : (
        <AlertCircle className="h-3 w-3 flex-none" />
      )}
      {duration && chip.stepKeys.length === 1 && (
        <span className="text-[10px] tabular-nums text-[var(--color-text-dim)]">
          {duration}
        </span>
      )}
    </button>
  );
}

/** One step's compact chip (used inside the open timeline). */
export function ToolChip({
  step,
  def,
  onClick,
}: {
  step: RunStep;
  def: ToolCardDefinition;
  onClick: () => void;
}) {
  return <ChipPill chip={chipForStep(step, def)} onClick={onClick} entering />;
}

/**
 * The completed-group header strip: merged chips ordered by importance
 * and wrapping freely, then a "+N more" pill. The count cap is the only
 * overflow mechanism, so nothing is ever clipped. Picking a chip reports
 * the first step it covers so the group can open and expand that card.
 */
export function ToolChipStrip({
  steps,
  onPick,
  max = MAX_STRIP_CHIPS,
  className,
}: {
  steps: RunStep[];
  onPick: (stepKey: string) => void;
  max?: number;
  className?: string;
}) {
  const chips = orderChips(mergeChips(steps));
  const visible = chips.slice(0, max);
  const hidden = chips.slice(max);
  return (
    <div
      data-testid="chat-tool-chip-strip"
      className={`flex min-w-0 flex-wrap items-center gap-1.5 ${className ?? ""}`}
    >
      {visible.map((chip) => (
        <ChipPill key={chip.key} chip={chip} onClick={() => onPick(chip.stepKeys[0])} />
      ))}
      {hidden.length > 0 && (
        <button
          type="button"
          data-testid="chat-tool-chip-more"
          onClick={() => onPick(hidden[0].stepKeys[0])}
          className="inline-flex h-6 items-center rounded-full border border-dashed border-[var(--color-border)] px-2 text-[11px] leading-none text-[var(--color-text-dim)] hover:text-[var(--color-text-muted)]"
        >
          +{hidden.length} more
        </button>
      )}
    </div>
  );
}
