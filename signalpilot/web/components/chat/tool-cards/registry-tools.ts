import {
  BookOpen,
  Braces,
  CircleCheck,
  Columns3,
  FileText,
  Layers,
  SquareTerminal,
  Table2,
  TableProperties,
  Upload,
  Waypoints,
  type LucideIcon,
} from "lucide-react";
import {
  normalizeToolName,
  toolResultKindForTool,
  type RunStep,
} from "~/lib/chat-run-steps";
import type { ToolCardAccent, ToolCardKind } from "./registry";

/**
 * Step → card kind resolution, kept apart from the registry so the pure
 * mapping is testable without any card module loaded.
 */

/** Step categories that are not tool calls with a projectable result. */
const NON_CARD_CATEGORIES = new Set<RunStep["category"]>([
  "subagent",
  "dashboard",
  "approval",
  "plan",
  "progress",
  "error",
]);

/**
 * The card kind for a step, or null when it should keep the legacy row.
 * Order: a projected result wins; else the kind the tool is known to
 * produce; else `legacy` for MCP tools (generic card). Claude-code tools
 * other than Bash (Read/Write/Edit/TodoWrite…) always return null.
 */
export function cardKindForStep(step: RunStep): ToolCardKind | null {
  if (!step.tool || NON_CARD_CATEGORIES.has(step.category)) return null;
  const tool = step.tool.startsWith("mcp__")
    ? normalizeToolName(step.tool).tool
    : step.tool;
  if (step.toolOrigin === "claude-code" && tool !== "Bash") return null;
  if (step.result && step.result.kind !== "legacy") return step.result.kind;
  return toolResultKindForTool(tool) ?? "legacy";
}

export const ACCENT_BY_KIND: Record<ToolCardKind, ToolCardAccent> = {
  table: "data",
  table_list: "schema",
  schema: "schema",
  column_profile: "schema",
  validation: "check",
  dbt_run: "dbt",
  terminal: "shell",
  knowledge: "knowledge",
  artifact: "artifact",
  json: "neutral",
  text: "neutral",
  legacy: "neutral",
};

export const ICON_BY_KIND: Record<ToolCardKind, LucideIcon> = {
  table: Table2,
  table_list: Layers,
  schema: TableProperties,
  column_profile: Columns3,
  validation: CircleCheck,
  dbt_run: Waypoints,
  terminal: SquareTerminal,
  knowledge: BookOpen,
  artifact: Upload,
  json: Braces,
  text: FileText,
  legacy: FileText,
};

/** Singular noun per kind for merged chips ("3 queries"). */
export const NOUN_BY_KIND: Record<ToolCardKind, string> = {
  table: "query",
  table_list: "listing",
  schema: "schema",
  column_profile: "profile",
  validation: "check",
  dbt_run: "dbt run",
  terminal: "command",
  knowledge: "lookup",
  artifact: "artifact",
  json: "tool call",
  text: "tool call",
  legacy: "tool call",
};

export function accentForKind(kind: ToolCardKind): ToolCardAccent {
  return ACCENT_BY_KIND[kind] ?? "neutral";
}

export function iconForKind(kind: ToolCardKind): LucideIcon {
  return ICON_BY_KIND[kind] ?? FileText;
}
