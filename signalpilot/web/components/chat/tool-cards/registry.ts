import type { LucideIcon } from "lucide-react";
import type { ComponentType } from "react";
import type { RunStep, ToolResult, ToolResultKind } from "~/lib/chat-run-steps";
import { accentForKind, cardKindForStep, iconForKind } from "./registry-tools";

/**
 * The tool-card registry. Each result kind registers one definition at
 * module load (see `cards/index.ts`); `resolveToolCard` picks the card for
 * a step. Kinds without a dedicated card fall back to the generic card so
 * the timeline never regresses to nothing.
 */

/** Colour family; mapped to `--chat-tool-accent` in tool-cards.css. */
export type ToolCardAccent =
  | "data"
  | "schema"
  | "check"
  | "dbt"
  | "shell"
  | "knowledge"
  | "artifact"
  | "neutral";

/** Registry key: every wire kind plus the pre-projector `legacy` marker. */
export type ToolCardKind = ToolResultKind | "legacy";

export type ToolCardSummary = {
  /** Short human title, e.g. "Query" / "Discovered tables". */
  title: string;
  /** Mono tabular stat, e.g. "1,204 rows · 312 ms"; null when unknown. */
  stat: string | null;
  /** False when the step failed or the result reports failure. */
  ok: boolean;
};

export type ToolCardContext = {
  step: RunStep;
  result: ToolResult | null;
  conversationId: string | null;
  openArtifact: (fileId: string) => void;
  /** True when the step is the last one in its activity group. */
  isLastInGroup: boolean;
};

export type ToolCardDefinition = {
  kind: ToolCardKind;
  Icon: LucideIcon;
  accent: ToolCardAccent;
  /** Pure: drives the compact chip and the expanded frame header. */
  summarize: (step: RunStep) => ToolCardSummary;
  /** Body while the tool is still running (input echo, skeletons). */
  Running: ComponentType<ToolCardContext>;
  /** Body once the result landed (or the failure banner context). */
  Expanded: ComponentType<ToolCardContext>;
  /**
   * Keep the card expanded after completion while its group is still live,
   * e.g. the trailing table of a chain. Errors always stay open regardless.
   */
  stayOpenOnComplete?: (step: RunStep, isLastInGroup: boolean) => boolean;
};

const definitions = new Map<ToolCardKind, ToolCardDefinition>();

/** Kinds the generic card serves when nothing more specific is registered. */
export const GENERIC_CARD_KINDS: readonly ToolCardKind[] = ["json", "text", "legacy"];

export function registerToolCard(def: ToolCardDefinition): void {
  definitions.set(def.kind, def);
}

export function getToolCardDefinition(kind: ToolCardKind): ToolCardDefinition | null {
  return definitions.get(kind) ?? null;
}

/** Registered kinds, for tests and the strip's per-kind nouns. */
export function registeredToolCardKinds(): ToolCardKind[] {
  return [...definitions.keys()];
}

/**
 * The card for a step, or null when the step keeps the legacy `StepBody`
 * row (claude-code file/todo tools, non-tool steps). A kind with no
 * dedicated card yet resolves to the generic card, re-keyed to the real
 * kind so testids and accents stay honest.
 */
export function resolveToolCard(step: RunStep): ToolCardDefinition | null {
  const kind = cardKindForStep(step);
  if (!kind) return null;
  const exact = definitions.get(kind);
  if (exact) return exact;
  const generic = definitions.get("legacy");
  if (!generic) return null;
  return { ...generic, kind, accent: accentForKind(kind), Icon: iconForKind(kind) };
}
