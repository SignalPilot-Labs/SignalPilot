import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { RunStep, ToolResult } from "~/lib/chat-run-steps";
import { mergeChips, orderChips, parseStat, ToolChipStrip } from "./tool-chip";
import "./cards";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const tableResult = (summary: string): ToolResult => ({
  kind: "table",
  summary,
  resultText: null,
  resultChars: null,
  truncated: false,
  errorMessage: null,
  columns: [],
  rows: [],
  previewRowCount: 0,
  rowCount: null,
  queryRowCount: null,
  previewTruncated: false,
  columnsTruncated: false,
  resultId: null,
  executionId: null,
  executionMs: null,
  completeness: "unknown",
  truncationReason: null,
  piiRedactedColumns: [],
  source: "parsed",
});

function step(
  key: string,
  tool: string,
  overrides: Partial<RunStep> = {},
): RunStep {
  return {
    key,
    sequence: 1,
    category: tool === "query_database" ? "sql" : "generic",
    status: "succeeded",
    title: tool === "query_database" ? "Queried the warehouse" : tool,
    tool,
    toolOrigin: "signalpilot",
    input: null,
    sql: null,
    code: null,
    file: null,
    sources: [],
    detail: null,
    result: null,
    startedAt: "2026-09-01T12:00:00.000Z",
    endedAt: "2026-09-01T12:00:01.000Z",
    durationMs: 1_000,
    children: [],
    subagentType: null,
    report: null,
    liveText: "",
    ...overrides,
  };
}

describe("parseStat", () => {
  it("reads the leading number and unit", () => {
    expect(parseStat("1,204 rows · 312 ms")).toEqual({ value: 1204, unit: "rows" });
    expect(parseStat("47 tables · 3 databases")).toEqual({ value: 47, unit: "tables" });
  });
  it("returns null for stats without a leading count", () => {
    expect(parseStat("exit 0")).toBeNull();
    expect(parseStat(null)).toBeNull();
  });
});

describe("mergeChips", () => {
  it("merges consecutive successful chips of one kind and sums a shared unit", () => {
    const chips = mergeChips([
      step("a", "query_database", { result: tableResult("1,204 rows · 312 ms") }),
      step("b", "query_database", { result: tableResult("1,206 rows · 100 ms") }),
      step("c", "query_database", { result: tableResult("0 rows · 5 ms") }),
    ]);
    expect(chips).toHaveLength(1);
    expect(chips[0].title).toBe("3 queries");
    expect(chips[0].stat).toBe("2,410 rows");
    expect(chips[0].stepKeys).toEqual(["a", "b", "c"]);
  });

  it("counts without a stat when units differ", () => {
    const chips = mergeChips([
      step("a", "query_database", { result: tableResult("1,204 rows") }),
      step("b", "query_database", { result: tableResult("312 ms") }),
    ]);
    expect(chips[0].title).toBe("2 queries");
    expect(chips[0].stat).toBeNull();
  });

  it("never merges a failed chip", () => {
    const chips = mergeChips([
      step("a", "query_database", { result: tableResult("10 rows") }),
      step("b", "query_database", { status: "failed", detail: "boom" }),
      step("c", "query_database", { result: tableResult("20 rows") }),
    ]);
    expect(chips.map((chip) => chip.ok)).toEqual([true, false, true]);
    expect(chips).toHaveLength(3);
  });

  it("gives legacy claude-code rows a neutral chip keyed by category", () => {
    const chips = mergeChips([
      step("w1", "Write", { category: "file-write", toolOrigin: "claude-code", title: "Generated a file", file: "a.py" }),
      step("w2", "Write", { category: "file-write", toolOrigin: "claude-code", title: "Generated a file", file: "b.py" }),
    ]);
    expect(chips).toHaveLength(1);
    expect(chips[0].group).toBe("cat:file-write");
    expect(chips[0].title).toBe("2 files");
  });
});

describe("orderChips", () => {
  it("puts failed chips first, then kinds by priority, legacy last", () => {
    const chips = orderChips(
      mergeChips([
        step("r", "Read", { category: "file-read", toolOrigin: "claude-code", title: "Read a file" }),
        step("k", "search_knowledge", { title: "Looked up the knowledge base" }),
        step("q", "query_database", { result: tableResult("10 rows") }),
        step("v", "validate_sql", { status: "failed", detail: "boom" }),
        step("l", "list_tables", { title: "Listed tables" }),
      ]),
    );
    expect(chips.map((chip) => chip.key)).toEqual(["v", "q", "l", "k", "r"]);
  });
});

describe("ToolChipStrip", () => {
  let container: HTMLDivElement;
  let root: Root;
  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });
  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  it("folds chips past the cap into +N more and reports the picked step", async () => {
    const onPick = vi.fn();
    // Nine distinct kinds so nothing merges.
    const tools = [
      "query_database", "list_tables", "describe_table", "explore_columns",
      "validate_sql", "dbt_execute", "sandbox_exec", "search_knowledge", "start_analysis_notebook",
    ];
    const steps = tools.map((tool, i) => step(`s${i}`, tool, { title: `Tool ${i}` }));
    await act(async () => {
      root.render(<ToolChipStrip steps={steps} onPick={onPick} max={6} />);
    });
    const chips = container.querySelectorAll('[data-testid="chat-tool-chip"]');
    expect(chips).toHaveLength(6);
    const more = container.querySelector('[data-testid="chat-tool-chip-more"]');
    expect(more?.textContent).toBe("+3 more");
    await act(async () => {
      (chips[1] as HTMLButtonElement).click();
    });
    expect(onPick).toHaveBeenCalledWith("s1");
    await act(async () => {
      (more as HTMLButtonElement).click();
    });
    expect(onPick).toHaveBeenLastCalledWith("s6");
  });

  it("shows a table chip first even after five legacy chips, hiding nothing", async () => {
    const legacy: Array<[string, RunStep["category"], string]> = [
      ["TodoWrite", "todo", "Planned the work"],
      ["Read", "file-read", "Read a file"],
      ["Write", "file-write", "Generated a file"],
      ["Edit", "file-edit", "Edited a file"],
      ["Agent", "subagent", "Explored the project"],
    ];
    const steps = legacy.map(([tool, category, title], i) =>
      step(`l${i}`, tool, { category, toolOrigin: "claude-code", title }),
    );
    steps.push(step("q", "query_database", { result: tableResult("1,204 rows · 312 ms") }));
    await act(async () => {
      root.render(<ToolChipStrip steps={steps} onPick={() => {}} max={6} />);
    });
    const strip = container.querySelector('[data-testid="chat-tool-chip-strip"]');
    expect(strip?.className).not.toMatch(/max-h|overflow-hidden/);
    const chips = container.querySelectorAll('[data-testid="chat-tool-chip"]');
    expect(chips).toHaveLength(6);
    expect(container.querySelector('[data-testid="chat-tool-chip-more"]')).toBeNull();
    expect(chips[0].getAttribute("data-kind")).toBe("table");
    expect(chips[0].textContent).toContain("1,204 rows");
    for (let i = 1; i < chips.length; i += 1) {
      expect(chips[i].getAttribute("data-kind")).toBe("legacy");
    }
  });
});
