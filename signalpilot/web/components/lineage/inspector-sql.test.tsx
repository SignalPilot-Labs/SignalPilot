import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { COLLAPSE_LINES, InspectorSql, foldSql } from "./inspector-sql";
import type { ModelSqlState } from "./use-dbt-map";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const q = (testId: string) => document.querySelector(`[data-testid="${testId}"]`);

const ready = (over: Partial<Extract<ModelSqlState, { state: "ready" }>["sql"]> = {}): ModelSqlState => ({
  state: "ready",
  sql: {
    unique_id: "model.demo.fct_orders",
    name: "fct_orders",
    path: "facts/fct_orders.sql",
    original_file_path: "models/facts/fct_orders.sql",
    language: "sql",
    raw_sql: "select order_id from {{ ref('stg_orders') }}",
    compiled_sql: "select order_id from demo.analytics.stg_orders",
    source: "manifest",
    ...over,
  },
});

describe("foldSql", () => {
  it("keeps short bodies whole and folds long ones", () => {
    expect(foldSql("a\nb", false)).toEqual({ shown: "a\nb", hidden: 0 });
    const long = Array.from({ length: COLLAPSE_LINES + 30 }, (_, i) => `line ${i}`).join("\n");
    const folded = foldSql(long, false);
    expect(folded.hidden).toBe(30);
    expect(folded.shown.split("\n")).toHaveLength(COLLAPSE_LINES);
    expect(foldSql(long, true).hidden).toBe(0);
  });
});

describe("InspectorSql", () => {
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
    vi.restoreAllMocks();
  });

  async function render(state: ModelSqlState) {
    await act(async () => {
      root.render(<InspectorSql state={state} modelName="fct_orders" />);
    });
  }

  it("shows a skeleton while loading", async () => {
    await render({ state: "loading" });
    expect(q("inspector-sql-loading")).not.toBeNull();
    expect(q("inspector-sql")).toBeNull();
  });

  it("renders raw SQL by default with the path caption and a compiled toggle", async () => {
    await render(ready());
    const block = q("inspector-sql")!;
    expect(block.getAttribute("data-variant")).toBe("raw");
    expect(block.querySelector("pre.chat-code")?.textContent).toContain("ref('stg_orders')");
    expect(q("inspector-sql-path")?.textContent).toBe("models/facts/fct_orders.sql");
    // Highlighted: keywords are wrapped in token spans.
    expect(block.querySelector("pre .tok-keyword")?.textContent?.toLowerCase()).toBe("select");

    const compiled = Array.from(block.querySelectorAll("button")).find((b) => b.textContent === "compiled")!;
    await act(async () => compiled.click());
    expect(q("inspector-sql")?.getAttribute("data-variant")).toBe("compiled");
    expect(q("inspector-sql")?.querySelector("pre")?.textContent).toContain("demo.analytics.stg_orders");
  });

  it("hides the toggle when no compiled SQL exists", async () => {
    await render(ready({ compiled_sql: null }));
    expect(document.querySelector('[aria-label="SQL variant"]')).toBeNull();
    expect(q("inspector-sql")?.getAttribute("data-variant")).toBe("raw");
  });

  it("copies the visible body", async () => {
    const writeText = vi.fn(() => Promise.resolve());
    Object.assign(navigator, { clipboard: { writeText } });
    await render(ready());
    const copy = document.querySelector('button[aria-label="Copy"]') as HTMLButtonElement;
    await act(async () => copy.click());
    expect(writeText).toHaveBeenCalledWith("select order_id from {{ ref('stg_orders') }}");
  });

  it("folds long bodies behind Show more", async () => {
    const long = Array.from({ length: COLLAPSE_LINES + 5 }, (_, i) => `select ${i}`).join("\n");
    await render(ready({ raw_sql: long, compiled_sql: null }));
    const fold = q("inspector-sql-fold")!;
    expect(fold.textContent).toBe("Show more (5 more lines)");
    expect(q("inspector-sql")?.querySelector("pre")?.textContent).not.toContain(`select ${COLLAPSE_LINES + 4}`);
    await act(async () => (fold as HTMLButtonElement).click());
    expect(q("inspector-sql")?.querySelector("pre")?.textContent).toContain(`select ${COLLAPSE_LINES + 4}`);
    expect(q("inspector-sql-fold")?.textContent).toBe("Show less");
  });

  it("shows the quiet unavailable state and the error state", async () => {
    await render({ state: "unavailable" });
    expect(q("inspector-sql-unavailable")?.textContent).toBe("SQL not available for this node.");
    await render(ready({ raw_sql: null, compiled_sql: null }));
    expect(q("inspector-sql-unavailable")).not.toBeNull();
    await render({ state: "error" });
    expect(q("inspector-sql-error")?.textContent).toContain("fct_orders");
  });
});
