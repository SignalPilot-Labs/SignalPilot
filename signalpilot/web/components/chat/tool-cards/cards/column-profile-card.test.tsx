import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { ColumnProfileResult, ProfiledColumn, RunStep } from "~/lib/chat-run-steps";
import { ToolCard } from "../tool-card";
import { columnsFromInput, summarizeColumnProfile } from "./column-profile-card";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

function profiled(name: string, extra: Partial<ProfiledColumn> = {}): ProfiledColumn {
  return {
    name,
    type: "varchar",
    primaryKey: false,
    nullable: null,
    comment: null,
    distinctCount: null,
    uniqueness: null,
    min: null,
    max: null,
    avg: null,
    nullCount: null,
    nullPct: null,
    sampleValues: [],
    topValues: [],
    ...extra,
  };
}

const TIER = profiled("tier", {
  nullable: true,
  distinctCount: 4,
  uniqueness: 0.0000019,
  nullCount: 61_402,
  nullPct: 2.9,
  sampleValues: ["enterprise", "mid-market", "smb", "marketplace"],
  topValues: [
    { value: "smb", count: 1_004_331 },
    { value: "mid-market", count: 612_004 },
    { value: "enterprise", count: 341_882 },
    { value: "marketplace", count: 124_263 },
  ],
});

const NET_REVENUE = profiled("net_revenue", {
  type: "numeric(18,2)",
  nullable: false,
  distinctCount: 418_211,
  uniqueness: 0.195,
  min: "0.00",
  max: "184,220.00",
  avg: "7,512.40",
  nullCount: 0,
  nullPct: 0,
  topValues: [
    { value: "49.00", count: 41_203 },
    { value: "99.00", count: 38_115 },
  ],
});

function profileResult(overrides: Partial<ColumnProfileResult> = {}): ColumnProfileResult {
  return {
    kind: "column_profile",
    summary: "Profiled 4 columns of analytics.fct_orders",
    resultText: "tier (varchar): distinct=4",
    resultChars: 26,
    truncated: false,
    errorMessage: null,
    table: "analytics.fct_orders",
    rowCount: 2_143_882,
    filter: null,
    columns: [
      profiled("region_id", { type: "integer", distinctCount: 3, min: "1", max: "3", nullPct: 0 }),
      NET_REVENUE,
      TIER,
      profiled("order_quarter", { distinctCount: 7, min: "2024-Q1", max: "2025-Q3", nullPct: 0 }),
    ],
    columnsTruncated: false,
    ...overrides,
  };
}

function step(overrides: Partial<RunStep> = {}): RunStep {
  return {
    key: "s3",
    sequence: 3,
    category: "source",
    status: "succeeded",
    title: "Profiled columns",
    tool: "explore_columns",
    toolOrigin: "signalpilot",
    input: {
      connection_name: "warehouse_prod",
      table: "analytics.fct_orders",
      columns: ["region_id", "net_revenue", "tier", "order_quarter"],
    },
    sql: null,
    code: null,
    file: null,
    sources: [],
    detail: null,
    result: null,
    startedAt: "2026-09-01T12:00:00.000Z",
    endedAt: "2026-09-01T12:00:01.000Z",
    durationMs: 900,
    children: [],
    subagentType: null,
    report: null,
    liveText: "",
    ...overrides,
  };
}

const q = (root: ParentNode, selector: string) => root.querySelector(selector);
const qa = (root: ParentNode, selector: string) => [...root.querySelectorAll(selector)];

describe("summarizeColumnProfile", () => {
  it("counts columns of the table", () => {
    expect(summarizeColumnProfile(step({ result: profileResult() }))).toEqual({
      title: "Column profile",
      stat: "4 columns of analytics.fct_orders",
      ok: true,
    });
  });
  it("describes a single column inline", () => {
    const result = profileResult({
      columns: [profiled("order_status", { distinctCount: 12, nullPct: 2.1 })],
    });
    expect(summarizeColumnProfile(step({ result })).stat).toBe(
      "order_status · 12 distinct · 2.1% null",
    );
  });
  it("has no stat for a legacy result", () => {
    expect(summarizeColumnProfile(step()).stat).toBeNull();
  });
  it("reads column names from list or comma-separated input", () => {
    expect(columnsFromInput(step())).toEqual(["region_id", "net_revenue", "tier", "order_quarter"]);
    expect(columnsFromInput(step({ input: { column: "tier, region_id" } }))).toEqual([
      "tier",
      "region_id",
    ]);
    expect(columnsFromInput(step({ input: null }))).toEqual([]);
  });
});

describe("column_profile card", () => {
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

  it("renders the requested columns as pills over ghost bars while running", async () => {
    await render(step({ status: "running", endedAt: null, durationMs: null }));
    const card = q(container, '[data-testid="chat-tool-card-column_profile"]');
    expect(card?.textContent).toContain("analytics.fct_orders");
    expect(card?.textContent).toContain("net_revenue");
    expect(card?.textContent).toContain("order_quarter");
    expect(card?.textContent).toContain("Profiling columns…");
    expect(qa(container, ".animate-shimmer").length).toBeGreaterThan(0);
  });

  it("shows the stat on the chip and expands into per-column blocks", async () => {
    await render(step({ result: profileResult() }));
    expect(q(container, '[data-testid="chat-tool-chip"]')?.textContent).toContain(
      "4 columns of analytics.fct_orders",
    );
    await expand();
    expect(q(container, '[data-testid="chat-column-profile"]')).not.toBeNull();
    const blocks = qa(container, '[data-testid="chat-column-profile-column"]');
    expect(blocks).toHaveLength(4);

    const revenue = blocks[1];
    expect(revenue.textContent).toContain("net_revenue");
    expect(revenue.textContent).toContain("numeric(18,2)");
    expect(revenue.textContent).toContain("distinct418,211");
    expect(revenue.textContent).toContain("unique20%");
    expect(revenue.textContent).toContain("min0.00");
    expect(revenue.textContent).toContain("max184,220.00");
    expect(revenue.textContent).toContain("avg7,512.40");
    expect(revenue.textContent).toContain("null0%");

    const tier = blocks[2];
    expect(tier.textContent).toContain("nullable");
    expect(tier.textContent).toContain("unique<1%");
    expect(tier.textContent).toContain("null2.9%");
    const bars = qa(tier, '[data-testid="chat-column-profile-bar"]') as HTMLElement[];
    expect(bars).toHaveLength(4);
    expect(bars[0].style.width).toBe("100%");
    expect(Number.parseFloat(bars[1].style.width)).toBeCloseTo(60.9, 0);
    expect(bars[0].classList.contains("chat-tool-bar-grow")).toBe(true);
    expect(bars[3].style.animationDelay).toBe("120ms");
    expect(tier.textContent).toContain("1,004,331");
    const samples = q(tier, '[data-testid="chat-column-profile-samples"]');
    expect(samples?.textContent).toContain("marketplace");
    expect(qa(samples!, "span")).toHaveLength(4);
    // No bars or samples for a column without them.
    expect(qa(blocks[0], '[data-testid="chat-column-profile-bar"]')).toHaveLength(0);
    expect(q(blocks[0], '[data-testid="chat-column-profile-samples"]')).toBeNull();
  });

  it("renders the table meta line and the truncation footer", async () => {
    await render(step({ result: profileResult({ columnsTruncated: true, filter: "tier = 'smb'" }) }));
    await expand();
    const card = q(container, '[data-testid="chat-column-profile"]');
    expect(card?.textContent).toContain("2,143,882 rows");
    expect(card?.textContent).toContain("where tier = 'smb'");
    expect(card?.textContent).toContain("more columns not shown");
    expect(q(container, '[data-testid="chat-tool-chip"]')).toBeNull();
  });

  it("degrades a legacy result to the input list", async () => {
    await render(step());
    await expand();
    expect(q(container, '[data-testid="chat-column-profile"]')).toBeNull();
    const card = q(container, '[data-testid="chat-tool-card-column_profile"]');
    expect(card?.textContent).toContain("connection_name");
    expect(card?.textContent).toContain("warehouse_prod");
  });
});
