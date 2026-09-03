import { asRecord, text } from "./payload";
import type { RunStep, RunStepCategory } from "./types";

const SQL_TOOLS = new Set([
  "query_database",
  "explain_query",
  "validate_sql",
  "plan_query",
  "preview_query",
]);
const PYTHON_TOOLS = new Set(["run_cells"]);
const NOTEBOOK_TOOLS = new Set([
  "start_analysis_notebook",
  "edit_notebook",
  "save_data_snapshot",
]);
const FILE_WRITE_TOOLS = new Set(["Write", "NotebookEdit"]);
const FILE_EDIT_TOOLS = new Set(["Edit", "MultiEdit"]);
const FILE_READ_TOOLS = new Set(["Read", "Glob", "Grep", "LS"]);
const WEB_TOOLS = new Set(["WebFetch", "WebSearch"]);

/** Tool names that spawn a subagent whose work is grouped under the spawn. */
export const SUBAGENT_SPAWN_TOOLS = new Set(["Agent", "Task"]);

export function normalizeToolName(raw: string): {
  tool: string;
  origin: RunStep["toolOrigin"];
} {
  const match = /^mcp__([^_]+(?:[-_][^_]+)*?)__(.+)$/.exec(raw);
  if (!match) return { tool: raw, origin: "claude-code" };
  const server = match[1];
  const tool = match[2];
  if (server.includes("notebook")) return { tool, origin: "notebook" };
  if (server.includes("standalone") || server.includes("chat")) {
    return { tool, origin: "chat" };
  }
  return { tool, origin: "signalpilot" };
}

export function categorizeTool(tool: string): RunStepCategory {
  if (tool === "create_dashboard_preview") return "dashboard";
  if (SQL_TOOLS.has(tool)) return "sql";
  if (PYTHON_TOOLS.has(tool)) return "python";
  if (NOTEBOOK_TOOLS.has(tool)) return "notebook";
  if (tool === "Bash" || tool.startsWith("sandbox_")) return "terminal";
  if (FILE_WRITE_TOOLS.has(tool)) return "file-write";
  if (FILE_EDIT_TOOLS.has(tool)) return "file-edit";
  if (FILE_READ_TOOLS.has(tool)) return "file-read";
  if (tool === "TodoWrite") return "todo";
  if (WEB_TOOLS.has(tool)) return "web";
  if (tool === "inspect_dbt" || tool.startsWith("dbt_")) return "dbt";
  if (
    /schema|table|column|relationship|metric|model|source|lineage/.test(tool)
  ) {
    return "source";
  }
  return "generic";
}

export function humanizeTool(tool: string): string {
  const titles: Record<string, string> = {
    query_database: "Queried the warehouse",
    explain_query: "Explained query plan",
    validate_sql: "Validated SQL",
    plan_query: "Planned the query",
    run_cells: "Executed notebook cells",
    edit_notebook: "Edited the analysis notebook",
    start_analysis_notebook: "Started the analysis notebook",
    save_data_snapshot: "Saved a data snapshot",
    inspect_dbt: "Inspected the dbt project",
    dbt_execute: "Ran dbt against the warehouse",
    sandbox_exec: "Ran a command in the sandbox",
    sandbox_write_file: "Wrote a file in the sandbox",
    sandbox_read_file: "Read a file in the sandbox",
    create_dashboard_preview: "Creating dashboard preview",
    begin_dashboard_authoring: "Resolving dashboard fields",
    set_dashboard_plan: "Validating dashboard plan",
    upsert_dashboard_chart: "Validating dashboard chart",
    apply_dashboard_operations: "Applying dashboard refinements",
    Bash: "Ran a command",
    Write: "Generated a file",
    Edit: "Edited a file",
    MultiEdit: "Edited a file",
    Read: "Read a file",
    Glob: "Searched for files",
    Grep: "Searched file contents",
    TodoWrite: "Updated the plan",
    WebFetch: "Fetched a page",
    WebSearch: "Searched the web",
  };
  if (titles[tool]) return titles[tool];
  return tool
    .replaceAll("_", " ")
    .replace(/^[a-z]/, (letter) => letter.toUpperCase());
}

export function extractFile(
  tool: string,
  category: RunStepCategory,
  input: Record<string, unknown> | null,
): string | null {
  if (!input) return null;
  const candidate =
    text(input.file_path) ??
    text(input.filename) ??
    text(input.path) ??
    text(input.notebook_path) ??
    (category === "file-read" ? text(input.pattern) : null);
  if (candidate) return candidate;
  if (tool === "WebFetch" || tool === "WebSearch") {
    return text(input.url) ?? text(input.query);
  }
  return null;
}

export function extractCode(
  tool: string,
  input: Record<string, unknown> | null,
): string | null {
  if (!input) return null;
  if (tool === "Bash") return text(input.command);
  if (tool === "Write" || tool === "NotebookEdit") {
    return text(input.content) ?? text(input.new_source);
  }
  if (tool === "run_cells" || tool === "edit_notebook") {
    const cells = Array.isArray(input.cells) ? input.cells : null;
    if (cells) {
      const sources = cells
        .map((cell) => {
          const record = asRecord(cell);
          return (
            text(record?.source) ??
            text(record?.code) ??
            (typeof cell === "string" ? cell : null)
          );
        })
        .filter((value): value is string => Boolean(value));
      if (sources.length) return sources.join("\n\n");
    }
    return text(input.source) ?? text(input.code);
  }
  return null;
}

export function extractSources(
  input: Record<string, unknown> | null,
): string[] {
  if (!input) return [];
  const keys = [
    "metric_name",
    "model_name",
    "schema_name",
    "source_name",
    "table_name",
  ];
  return keys
    .map((key) => text(input[key]))
    .filter((value): value is string => Boolean(value));
}
