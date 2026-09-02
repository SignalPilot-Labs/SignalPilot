import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { RunStep, SchemaColumn, SchemaResult } from "~/lib/chat-run-steps";
import { ToolCard } from "../tool-card";
import { formatCompactCount, summarizeSchema } from "./schema-card";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

function column(name: string, type: string, extra: Partial<SchemaColumn> = {}): SchemaColumn {
  return {
    name,
    type,
    nullable: false,
    primaryKey: false,
    foreignKey: null,
    comment: null,
    pii: null,
    ...extra,
  };
}

function schemaResult(overrides: Partial<SchemaResult> = {}): SchemaResult {
  return {
    kind: "schema",
    summary: "analytics.fct_orders · 18 columns · 2.1M rows",
    resultText: "# analytics.fct_orders",
    resultChars: 22,
    truncated: false,
    errorMessage: null,
    table: "analytics.fct_orders",
    description: "One row per fulfilled order with net revenue after refunds.",
    owner: "data-platform",
    rowCount: 2_143_882,
    engine: "postgres",
    columns: [
      column("order_id", "varchar", { primaryKey: true, comment: "Order surrogate key" }),
      column("customer_id", "varchar", { foreignKey: "analytics.dim_customers.customer_id" }),
      column("email", "varchar", { nullable: true, pii: "email" }),
      column("order_quarter", "varchar", { comment: "'2025-Q3' style label" }),
      column("net_revenue", "numeric(18,2)"),
      column("fulfilled_at", "timestamp", { nullable: true }),
    ],
    columnsTruncated: false,
    foreignKeys: [{ column: "customer_id", references: "analytics.dim_customers.customer_id" }],
    referencedBy: [
      { table: "analytics.rpt_daily_revenue", column: "order_id", referencesColumn: "order_id" },
    ],
    sampleValues: { order_quarter: ["2025-Q1", "2025-Q2", "2025-Q3"] },
    ...overrides,
  };
}

function step(overrides: Partial<RunStep> = {}): RunStep {
  return {
    key: "s2",
    sequence: 2,
    category: "source",
    status: "succeeded",
    title: "Read the table schema",
    tool: "get_table_schema",
    toolOrigin: "signalpilot",
    input: { connection_name: "warehouse_prod", table: "analytics.fct_orders" },
    sql: null,
    code: null,
    file: null,
    sources: [],
    detail: null,
    result: null,
    startedAt: "2026-09-01T12:00:00.000Z",
    endedAt: "2026-09-01T12:00:01.000Z",
    durationMs: 380,
    children: [],
    subagentType: null,
    report: null,
    liveText: "",
    ...overrides,
  };
}

const q = (root: ParentNode, selector: string) => root.querySelector(selector);
const qa = (root: ParentNode, selector: string) => [...root.querySelectorAll(selector)];

describe("summarizeSchema", () => {
  it("formats the column and compact row counts", () => {
    expect(summarizeSchema(step({ result: schemaResult() }))).toEqual({
      title: "Read the table schema",
      stat: "analytics.fct_orders · 6 columns · 2.1M rows",
      ok: true,
    });
    expect(summarizeSchema(step({ result: schemaResult({ rowCount: null }) })).stat).toBe(
      "analytics.fct_orders · 6 columns",
    );
  });
  it("falls back to the input table for a legacy result", () => {
    expect(summarizeSchema(step())).toEqual({
      title: "Read the table schema",
      stat: "analytics.fct_orders",
      ok: true,
    });
  });
  it("compacts counts", () => {
    expect(formatCompactCount(812)).toBe("812");
    expect(formatCompactCount(4_820)).toBe("4.8K");
    expect(formatCompactCount(48_210)).toBe("48K");
    expect(formatCompactCount(2_143_882)).toBe("2.1M");
  });
});

describe("schema card", () => {
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
  const render = async (s: RunStep) => {
    await act(async () => {
      root.render(
        <ol>
          <ToolCard step={s} groupLive isLastInGroup />
        </ol>,
      );
    });
  };
  const expand = async () => {
    const chip = q(container, '[data-testid="chat-tool-chip"]') as HTMLButtonElement;
    await act(async () => chip.click());
  };

  it("renders the table headline and ghost rows while running", async () => {
    await render(step({ status: "running", endedAt: null, durationMs: null }));
    const card = q(container, '[data-testid="chat-tool-card-schema"]');
    expect(card?.textContent).toContain("analytics.fct_orders");
    expect(card?.textContent).toContain("Reading the catalog…");
    expect(qa(container, ".animate-shimmer").length).toBe(18);
  });

  it("shows the stat on the chip and expands into the columns table", async () => {
    await render(step({ result: schemaResult() }));
    expect(q(container, '[data-testid="chat-tool-chip"]')?.textContent).toContain(
      "6 columns · 2.1M rows",
    );
    await expand();
    const card = q(container, '[data-testid="chat-tool-card-schema"]');
    expect(card?.textContent).toContain("One row per fulfilled order");
    expect(card?.textContent).toContain("owner data-platform");
    expect(card?.textContent).toContain("postgres");
    expect(q(container, '[data-testid="chat-schema-card-columns"]')).not.toBeNull();
    const rows = qa(container, '[data-testid="chat-schema-card-row"]');
    expect(rows).toHaveLength(6);
    expect(rows[0].textContent).toContain("order_id");
    expect(rows[0].textContent).toContain("PK");
    expect(rows[0].textContent).toContain("Order surrogate key");
    expect(rows[1].textContent).toContain("FK");
    expect(rows[1].textContent).toContain("dim_customers.customer_id");
    expect(rows[2].textContent).toContain("nullable");
    expect(rows[2].textContent).toContain("PII");
    expect(rows[4].textContent).not.toContain("nullable");
    expect(rows[0].classList.contains("chat-tool-cascade-in")).toBe(true);
    expect((rows[3] as HTMLElement).style.getPropertyValue("--i")).toBe("3");
    // Sample values sit under their column.
    const samples = q(rows[3], '[data-testid="chat-schema-card-samples"]');
    expect(samples?.textContent).toBe("2025-Q1 · 2025-Q2 · 2025-Q3");
    expect(qa(container, '[data-testid="chat-schema-card-samples"]')).toHaveLength(1);
    // FK sections.
    expect(card?.textContent).toContain("Outgoing FKs");
    expect(card?.textContent).toContain("Referenced by");
    expect(card?.textContent).toContain("analytics.rpt_daily_revenue.order_id");
  });

  it("notes truncated columns and omits empty sections", async () => {
    await render(
      step({
        result: schemaResult({
          columnsTruncated: true,
          foreignKeys: [],
          referencedBy: [],
          sampleValues: {},
          description: null,
        }),
      }),
    );
    await expand();
    const card = q(container, '[data-testid="chat-tool-card-schema"]');
    expect(card?.textContent).toContain("more columns not shown");
    expect(card?.textContent).not.toContain("Outgoing FKs");
    expect(card?.textContent).not.toContain("Referenced by");
    expect(qa(container, '[data-testid="chat-schema-card-samples"]')).toHaveLength(0);
  });

  it("degrades a legacy result to the input list", async () => {
    await render(step());
    await expand();
    expect(q(container, '[data-testid="chat-schema-card-columns"]')).toBeNull();
    const card = q(container, '[data-testid="chat-tool-card-schema"]');
    expect(card?.textContent).toContain("connection_name");
    expect(card?.textContent).toContain("warehouse_prod");
  });
});
