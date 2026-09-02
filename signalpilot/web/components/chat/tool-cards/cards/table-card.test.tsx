import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ChatUiContext, type ChatUiContextValue } from "~/components/chat/chat-ui-context";
import type { RunStep, TableResult, ToolResult } from "~/lib/chat-run-steps";
import { getToolCardDefinition } from "../registry";
import { ToolCard } from "../tool-card";
import { summarizeTable } from "./table-card";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const SQL = `select region, sum(net_revenue) as revenue, count(*) as orders, avg(growth_pct) as growth
from analytics.fct_orders where order_quarter in ('2025-Q2','2025-Q3') and tier <> 'internal'
group by 1 order by 2 desc limit 50`;

const TOTAL = 1_204;
const columns = [
  { name: "order_id", logicalType: "string" },
  { name: "region", logicalType: "string" },
  { name: "email", logicalType: "string" },
  { name: "net_revenue", logicalType: "decimal" },
];
const row = (i: number) => [`ORD-${100_001 + i}`, ["AMER", "EMEA", "APAC"][i % 3], "[REDACTED]", i * 10.5];

function tableResult(overrides: Partial<TableResult> = {}): TableResult {
  return {
    kind: "table",
    summary: "1,204 rows · 312 ms",
    resultText: null,
    resultChars: null,
    truncated: false,
    errorMessage: null,
    columns,
    rows: Array.from({ length: 50 }, (_, i) => row(i)),
    previewRowCount: 50,
    rowCount: TOTAL,
    queryRowCount: TOTAL,
    previewTruncated: true,
    columnsTruncated: false,
    resultId: "res-31",
    executionId: "exec-1",
    executionMs: 312,
    completeness: "complete",
    truncationReason: null,
    piiRedactedColumns: ["email"],
    source: "structured",
    ...overrides,
  };
}

const legacyResult: ToolResult = {
  kind: "legacy",
  summary: null,
  resultText: null,
  resultChars: null,
  truncated: false,
  errorMessage: null,
};

function step(overrides: Partial<RunStep> = {}): RunStep {
  return {
    key: "s1",
    sequence: 1,
    category: "sql",
    status: "succeeded",
    title: "Queried the warehouse",
    tool: "query_database",
    toolOrigin: "signalpilot",
    input: { sql: SQL, connection: "warehouse_prod" },
    sql: SQL,
    code: null,
    file: null,
    sources: [],
    detail: null,
    result: tableResult(),
    startedAt: "2026-09-01T12:00:00.000Z",
    endedAt: "2026-09-01T12:00:00.312Z",
    durationMs: 312,
    children: [],
    subagentType: null,
    report: null,
    liveText: "",
    ...overrides,
  };
}

const q = (root: ParentNode, selector: string) => root.querySelector(selector);
const qa = (root: ParentNode, selector: string) => [...root.querySelectorAll(selector)];

describe("summarizeTable", () => {
  it("registers the table kind pinned open when last in group", () => {
    const def = getToolCardDefinition("table");
    expect(def?.accent).toBe("data");
    expect(def?.stayOpenOnComplete?.(step(), true)).toBe(true);
    expect(def?.stayOpenOnComplete?.(step(), false)).toBe(false);
  });
  it("formats the chip stat and marks partial results", () => {
    expect(summarizeTable(step())).toEqual({
      title: "Queried the warehouse",
      stat: "1,204 rows · 312 ms",
      ok: true,
    });
    expect(
      summarizeTable(step({ result: tableResult({ completeness: "truncated", executionMs: 1_400 }) }))
        .stat,
    ).toBe("1,204 rows · 1.4 s · partial");
    expect(summarizeTable(step({ result: legacyResult }))).toEqual({
      title: "Queried the warehouse",
      stat: null,
      ok: true,
    });
    // No structured counts: the worker's one-liner stands in.
    expect(
      summarizeTable(step({ result: tableResult({ rows: [], rowCount: null, summary: "12 rows" }) }))
        .stat,
    ).toBe("12 rows");
    expect(
      summarizeTable(
        step({ status: "failed", result: tableResult({ rows: [], rowCount: null, summary: "boom" }) }),
      ).stat,
    ).toBeNull();
    expect(summarizeTable(step({ tool: "explain_query", title: "Explained query plan", status: "failed" }))).toEqual({
      title: "Explained query plan",
      stat: "1,204 rows · 312 ms",
      ok: false,
    });
  });
});

describe("table card", () => {
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
  const render = async (
    s: RunStep,
    ui?: Partial<ChatUiContextValue>,
    focus?: number,
    last = true,
  ) => {
    const card: ReactNode = (
      <ol>
        <ToolCard step={s} groupLive isLastInGroup={last} focusRequested={focus} />
      </ol>
    );
    await act(async () => {
      root.render(
        ui ? <ChatUiContext.Provider value={ui as ChatUiContextValue}>{card}</ChatUiContext.Provider> : card,
      );
    });
  };

  it("running: prettified SQL folded to six lines, ghost rows and the live line", async () => {
    await render(step({ status: "running", result: null, endedAt: null, durationMs: null }));
    const card = q(container, '[data-testid="chat-tool-card-table"]');
    expect(card).not.toBeNull();
    expect(q(container, '[data-testid="chat-tool-card"]')?.getAttribute("data-density")).toBe(
      "running",
    );
    const sql = q(container, '[data-testid="chat-table-sql"]');
    expect(sql?.querySelector("pre")?.textContent).toContain("SELECT");
    expect(sql?.querySelector("pre")?.textContent?.split("\n")).toHaveLength(6);
    expect(sql?.textContent).toContain("Show all");
    expect(qa(container, ".animate-shimmer")).toHaveLength(20);
    expect(card?.textContent).toContain("Scanning the warehouse…");
    expect(q(container, '[data-testid="chat-data-table"]')).toBeNull();
  });

  it("completed: chip stat, then the expanded grid, footer and PII notice", async () => {
    await render(step(), undefined, undefined, false);
    const chip = q(container, '[data-testid="chat-tool-chip"]') as HTMLButtonElement;
    expect(chip.textContent).toContain("Queried the warehouse");
    expect(chip.textContent).toContain("1,204 rows · 312 ms");
    await act(async () => chip.click());
    expect(qa(container, '[data-testid="chat-data-table"] tbody tr')).toHaveLength(50);
    const sql = q(container, '[data-testid="chat-table-sql"] pre');
    expect(sql?.textContent?.split("\n")).toHaveLength(3);
    const footer = q(container, '[data-testid="chat-table-footer"]');
    expect(footer?.textContent).toContain("1,204 rows · 312 ms · showing 50");
    expect(footer?.textContent).toContain("Copy CSV");
    expect(q(container, '[data-testid="chat-table-pii"]')?.textContent).toContain("email");
    expect(q(container, '[data-testid="chat-table-partial"]')).toBeNull();
    expect(container.textContent).not.toContain("Open in Artifacts");
    expect(q(container, '[data-testid="chat-data-table-sort-net_revenue"]')).not.toBeNull();
  });

  it("stays expanded when it is the trailing step of a live group", async () => {
    await render(step());
    expect(q(container, '[data-testid="chat-tool-card"]')?.getAttribute("data-density")).toBe(
      "expanded",
    );
    expect(qa(container, '[data-testid="chat-data-table"] tbody tr')).toHaveLength(50);
  });

  it("warns on a truncated result", async () => {
    await render(
      step({
        result: tableResult({ completeness: "truncated", truncationReason: "row cap 1000" }),
      }),
      undefined,
      1,
    );
    const notice = q(container, '[data-testid="chat-table-partial"]');
    expect(notice?.textContent).toContain("truncated");
    expect(notice?.textContent).toContain("row cap 1000");
    expect(notice?.className).toContain("--color-warning");
  });

  it("load all: pages rows through the context stub and grows the grid", async () => {
    const getToolResultRows = vi.fn(async (id: string, opts?: { offset?: number; limit?: number }) => {
      expect(id).toBe("res-31");
      const start = opts?.offset ?? 0;
      const end = Math.min(TOTAL, start + (opts?.limit ?? 500));
      return {
        columns: columns.map((c) => ({ name: c.name, logical_type: c.logicalType })),
        rows: Array.from({ length: end - start }, (_, i) => row(start + i)),
        saved_row_count: TOTAL,
      };
    });
    await render(step(), { conversationId: "c1", getToolResultRows }, 1);
    const button = q(container, '[data-testid="chat-data-table-load-all"]') as HTMLButtonElement;
    expect(button.textContent).toContain("Load all 1,204 rows");
    await act(async () => button.click());
    expect(getToolResultRows).toHaveBeenCalledTimes(2);
    expect(qa(container, '[data-testid="chat-data-table"] tbody tr')).toHaveLength(200);
    expect(q(container, '[data-testid="chat-data-table-show-next"]')?.textContent).toContain(
      "1,004 hidden",
    );
    expect(q(container, '[data-testid="chat-data-table-load-all"]')).toBeNull();
    expect(q(container, '[data-testid="chat-table-footer"]')?.textContent).toContain(
      "showing 1,204",
    );
  });

  it("failed: SQL only plus the shared error banner", async () => {
    await render(
      step({
        status: "failed",
        detail: "relation fct_orders does not exist",
        result: tableResult({ rows: [], rowCount: null, errorMessage: "relation fct_orders does not exist" }),
      }),
    );
    expect(q(container, '[data-testid="chat-tool-card"]')?.getAttribute("data-density")).toBe(
      "expanded",
    );
    expect(q(container, '[data-testid="chat-table-sql"]')).not.toBeNull();
    expect(q(container, '[data-testid="chat-data-table"]')).toBeNull();
    expect(q(container, '[data-testid="chat-tool-error"]')?.textContent).toContain("does not exist");
  });

  it("legacy: the SQL block alone and a chip without a stat", async () => {
    await render(step({ result: legacyResult }), undefined, undefined, false);
    const chip = q(container, '[data-testid="chat-tool-chip"]') as HTMLButtonElement;
    expect(chip.textContent).toContain("Queried the warehouse");
    expect(chip.textContent).not.toContain("rows");
    await act(async () => chip.click());
    expect(q(container, '[data-testid="chat-table-sql"]')).not.toBeNull();
    expect(q(container, '[data-testid="chat-data-table"]')).toBeNull();
    expect(q(container, '[data-testid="chat-table-footer"]')).toBeNull();
  });
});
