import type { Plan, ToolKind } from "./types";

/**
 * Tool name → display metadata. Mirrors the categories the SignalPilot chat
 * uses for its tool cards so the panel and the chat agree on colour and icon.
 */

export function normalizeToolName(raw: string): string {
  const match = /^mcp__[^_]+(?:[-_][^_]+)*?__(.+)$/.exec(raw);
  return match?.[1] ?? raw;
}

const KIND_RULES: Array<[RegExp, ToolKind]> = [
  [/^(query_database|plan_query|explain_query|preview_query|query_history|estimate_query_cost)$/, "table"],
  [/^list_tables$/, "table_list"],
  [/^(validate_sql|verify_.*|validate_model_output|compare_join_types|audit_model_sources|check_model_schema|connection_health)$/, "validation"],
  [/^(dbt_.*|inspect_dbt|refresh_mart|get_dbt_profile)$/, "dbt_run"],
  [/^(Bash|sandbox_exec)$/, "terminal"],
  [/knowledge|^notion_/, "knowledge"],
  [/^(Write|Edit|MultiEdit|NotebookEdit|Read|Glob|Grep|LS|sandbox_write_file|sandbox_read_file|dashboard_.*|edit_notebook|save_data_snapshot|start_analysis_notebook|run_notebook|read_notebook|run_cells)$/, "file"],
  [/^TodoWrite$/, "plan"],
  [/^(WebFetch|WebSearch)$/, "web"],
  [/^(Agent|Task)$/, "subagent"],
  [/schema|table|column|relationship|join|metric|model|source|lineage|grain|date_boundaries|xata/, "schema"],
];

export function kindForTool(tool: string): ToolKind {
  for (const [pattern, kind] of KIND_RULES) if (pattern.test(tool)) return kind;
  return "generic";
}

/** Present-tense line for the Now slot while the tool runs. */
const PRESENT: Record<string, string> = {
  query_database: "Querying the warehouse",
  plan_query: "Planning the query",
  explain_query: "Explaining the query plan",
  validate_sql: "Validating SQL",
  list_tables: "Listing tables",
  describe_table: "Reading the table schema",
  explore_table: "Exploring a table",
  explore_columns: "Profiling columns",
  explore_column: "Profiling a column",
  schema_overview: "Mapping the schema",
  schema_link: "Linking schema references",
  get_relationships: "Tracing relationships",
  find_join_path: "Finding a join path",
  map_columns: "Mapping columns",
  analyze_grain: "Checking the grain",
  verify_model_values: "Verifying model values",
  verify_metric_conformance: "Checking metric conformance",
  dbt_execute: "Running dbt",
  inspect_dbt: "Inspecting the dbt project",
  refresh_mart: "Refreshing the mart",
  sandbox_exec: "Running a command",
  sandbox_write_file: "Writing a file",
  sandbox_read_file: "Reading a file",
  Bash: "Running a command",
  Write: "Writing a file",
  Edit: "Editing a file",
  MultiEdit: "Editing files",
  Read: "Reading a file",
  Glob: "Searching files",
  Grep: "Searching file contents",
  TodoWrite: "Updating the plan",
  WebFetch: "Fetching a page",
  WebSearch: "Searching the web",
  Agent: "Delegating to a subagent",
  Task: "Delegating to a subagent",
  search_knowledge: "Searching the knowledge base",
  get_knowledge: "Reading the knowledge base",
  read_knowledge: "Reading the knowledge base",
  propose_knowledge: "Proposing a knowledge entry",
  run_notebook: "Running the notebook",
  run_cells: "Executing notebook cells",
  dashboard_screenshot: "Rendering the dashboard",
  dashboard_sample_data: "Checking dashboard data",
};

export function presentLabel(tool: string): string {
  return PRESENT[tool] ?? `Running ${tool.replaceAll("_", " ")}`;
}

/** Short noun for the chip when the event carries no description. */
const NOUN: Record<ToolKind, string> = {
  table: "Query",
  table_list: "Tables",
  schema: "Schema",
  validation: "Check",
  dbt_run: "dbt",
  terminal: "Shell",
  knowledge: "Knowledge",
  file: "File",
  plan: "Plan",
  web: "Web",
  subagent: "Subagent",
  generic: "Tool",
};

export function nounForKind(kind: ToolKind): string {
  return NOUN[kind];
}

/** Cut a description to a chip-sized label at a word boundary. */
export function shortLabel(text: string, max = 28): string {
  const clean = text.trim().replace(/\s+/g, " ").replace(/[.\s]+$/, "");
  if (clean.length <= max) return clean;
  const cut = clean.slice(0, max);
  const space = cut.lastIndexOf(" ");
  return `${(space > max * 0.5 ? cut.slice(0, space) : cut).replace(/[,;:\s]+$/, "")}…`;
}

/** "1,204 rows · 0.4 s" → 1204; null when the summary names no row count. */
export function parseRows(summary: string): number | null {
  const match = /([\d,]+)\s+rows?\b/i.exec(summary);
  if (!match?.[1]) return null;
  const value = Number(match[1].replace(/,/g, ""));
  return Number.isFinite(value) ? value : null;
}

/** "Plan updated · 2/5 done" → {done: 2, total: 5}. */
export function parsePlan(summary: string): Plan | null {
  const match = /(\d+)\s*\/\s*(\d+)\s*done/i.exec(summary);
  if (!match?.[1] || !match[2]) return null;
  const total = Number(match[2]);
  return total > 0 ? { done: Math.min(Number(match[1]), total), total } : null;
}

/** Trim a worker summary to something a chip can carry. */
export function chipStat(summary: string | null | undefined, max = 24): string {
  if (!summary) return "";
  const first = summary.split("\n")[0]?.trim() ?? "";
  if (first.length <= max) return first;
  return `${first.slice(0, max - 1).trimEnd()}…`;
}
