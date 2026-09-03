import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { RunStep, TableListEntry, TableListResult } from "~/lib/chat-run-steps";
import { ToolCard } from "../tool-card";
import { summarizeTableList } from "./table-list-card";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

function entry(name: string, index: number): TableListEntry {
  return {
    name,
    rowCount: 1_000 + index * 1_204,
    rowCountLabel: null,
    columns: [
      { name: "id", primaryKey: true, references: null },
      { name: "customer_id", primaryKey: false, references: "dim_customers.customer_id" },
      { name: "region_id", primaryKey: false, references: "dim_regions.region_id" },
      { name: "order_date", primaryKey: false, references: null },
    ],
    columnsTruncated: false,
  };
}

function listResult(overrides: Partial<TableListResult> = {}): TableListResult {
  const entries = [
    ...Array.from({ length: 16 }, (_, i) => entry(`analytics.fct_${i}`, i)),
    ...Array.from({ length: 17 }, (_, i) => entry(`staging.stg_${i}`, i)),
    ...Array.from({ length: 14 }, (_, i) => entry(`raw.src_${i}`, i)),
  ];
  return {
    kind: "table_list",
    summary: "Discovered 47 tables · 3 schemas",
    resultText: "analytics.fct_0 …",
    resultChars: 20,
    truncated: false,
    errorMessage: null,
    connection: "warehouse_prod",
    database: "analytics_db",
    dbType: "postgres",
    total: entries.length,
    entries,
    entriesTruncated: false,
    databases: [
      { name: "analytics", tableCount: 16 },
      { name: "staging", tableCount: 17 },
      { name: "raw", tableCount: 14 },
    ],
    ...overrides,
  };
}

function step(overrides: Partial<RunStep> = {}): RunStep {
  return {
    key: "s1",
    sequence: 1,
    category: "source",
    status: "succeeded",
    title: "Listed tables",
    tool: "list_tables",
    toolOrigin: "signalpilot",
    input: { connection_name: "warehouse_prod", schema: "analytics" },
    sql: null,
    code: null,
    file: null,
    sources: [],
    detail: null,
    result: null,
    startedAt: "2026-09-01T12:00:00.000Z",
    endedAt: "2026-09-01T12:00:01.000Z",
    durationMs: 450,
    children: [],
    subagentType: null,
    report: null,
    liveText: "",
    ...overrides,
  };
}

const q = (root: ParentNode, selector: string) => root.querySelector(selector);
const qa = (root: ParentNode, selector: string) => [...root.querySelectorAll(selector)];

describe("summarizeTableList", () => {
  it("counts tables and databases", () => {
    expect(summarizeTableList(step({ result: listResult() })).stat).toBe("47 tables · 3 databases");
    expect(summarizeTableList(step({ result: listResult({ databases: [] }) })).stat).toBe(
      "47 tables",
    );
  });
  it("switches to the database-first stat when only databases came back", () => {
    const result = listResult({
      entries: [],
      total: 0,
      databases: Array.from({ length: 6 }, (_, i) => ({ name: `db_${i}`, tableCount: 321 + i })),
    });
    expect(summarizeTableList(step({ result })).stat).toBe("6 databases · 1,941 tables");
  });
  it("has no stat for a legacy result", () => {
    expect(summarizeTableList(step())).toEqual({
      title: "Discovered tables",
      stat: null,
      ok: true,
    });
  });
});

describe("table_list card", () => {
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

  it("renders the input pills, a ticking badge and ghost rows while running", async () => {
    await render(step({ status: "running", endedAt: null, durationMs: null }));
    const card = q(container, '[data-testid="chat-tool-card-table_list"]');
    expect(card).not.toBeNull();
    expect(card?.textContent).toContain("warehouse_prod");
    expect(card?.textContent).toContain("analytics");
    expect(q(container, '[data-testid="chat-table-list-ticker"]')).not.toBeNull();
    expect(q(container, ".chat-tool-count-tick")).not.toBeNull();
    expect(qa(container, ".animate-shimmer").length).toBeGreaterThan(0);
  });

  it("shows the stat on the chip and expands into grouped rows with a filter", async () => {
    await render(step({ result: listResult() }));
    const chip = q(container, '[data-testid="chat-tool-chip"]');
    expect(chip?.textContent).toContain("47 tables · 3 databases");
    await expand();
    expect(q(container, '[data-testid="chat-table-list"]')).not.toBeNull();
    const groups = qa(container, '[data-testid="chat-table-list-group"]');
    expect(groups.map((g) => g.textContent?.slice(0, 40))).toHaveLength(3);
    expect(groups[0].textContent).toContain("analytics_db.analytics");
    // Three groups: all open, every row visible with its stagger index capped.
    const rows = qa(container, '[data-testid="chat-table-list-row"]');
    expect(rows).toHaveLength(47);
    expect(rows[0].textContent).toContain("fct_0");
    expect(rows[0].textContent).toContain("4 cols");
    expect(rows[0].textContent).toContain("1,000 rows");
    expect(rows[0].textContent).toContain("pkid");
    expect(rows[0].textContent).toContain("fkcustomer_id");
    expect((rows[30] as HTMLElement).style.getPropertyValue("--i")).toBe("24");
    expect(rows[0].classList.contains("chat-tool-cascade-in")).toBe(true);

    const filter = q(container, '[data-testid="chat-table-list-filter"]') as HTMLInputElement;
    expect(filter).not.toBeNull();
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
      setter?.call(filter, "stg_1");
      filter.dispatchEvent(new Event("input", { bubbles: true }));
    });
    const filtered = qa(container, '[data-testid="chat-table-list-row"]');
    expect(filtered.map((r) => r.textContent)).toHaveLength(8); // stg_1, stg_10…stg_16
    expect(qa(container, '[data-testid="chat-table-list-group"]')).toHaveLength(1);
    expect(q(container, '[data-testid="chat-table-list-filter"]')).not.toBeNull();
  });

  it("collapses all but the first group past three schemas and toggles on click", async () => {
    const result = listResult({
      entries: ["a", "b", "c", "d"].flatMap((schema) =>
        [1, 2].map((i) => entry(`${schema}.t${i}`, i)),
      ),
      total: 8,
      databases: [],
    });
    await render(step({ result }));
    await expand();
    expect(q(container, '[data-testid="chat-table-list-filter"]')).toBeNull();
    expect(qa(container, '[data-testid="chat-table-list-row"]')).toHaveLength(2);
    const headers = qa(container, '[data-testid="chat-table-list-group"] button');
    expect(headers[1].getAttribute("aria-expanded")).toBe("false");
    await act(async () => (headers[1] as HTMLButtonElement).click());
    expect(qa(container, '[data-testid="chat-table-list-row"]')).toHaveLength(4);
  });

  it("renders the truncation footer", async () => {
    await render(step({ result: listResult({ total: 212, entriesTruncated: true }) }));
    await expand();
    expect(q(container, '[data-testid="chat-table-list"]')?.textContent).toContain("+165 more");
  });

  it("renders the database list when no entries came back", async () => {
    const result = listResult({
      entries: [],
      total: 0,
      databases: [
        { name: "prod", tableCount: 1_204 },
        { name: "staging", tableCount: 726 },
      ],
    });
    await render(step({ result }));
    expect(q(container, '[data-testid="chat-tool-chip"]')?.textContent).toContain(
      "2 databases · 1,930 tables",
    );
    await expand();
    const rows = qa(container, '[data-testid="chat-table-list-row"]');
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toContain("prod");
    expect(rows[0].textContent).toContain("1,204 tables");
  });

  it("degrades a legacy result to the input list", async () => {
    await render(step());
    await expand();
    const card = q(container, '[data-testid="chat-tool-card-table_list"]');
    expect(q(container, '[data-testid="chat-table-list"]')).toBeNull();
    expect(card?.textContent).toContain("warehouse_prod");
    expect(card?.textContent).toContain("connection_name");
  });
});
