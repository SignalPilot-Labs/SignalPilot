import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { DbtRunResult, RunStep } from "~/lib/chat-run-steps";
import { getToolCardDefinition } from "../registry";
import { ToolCard } from "../tool-card";
import { summarizeDbtRun, tallyStatuses } from "./dbt-run-card";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const LOG =
  "12:41:03  Running with dbt=1.9.1\n12:41:12  Done. PASS=12 WARN=0 ERROR=1 SKIP=0 TOTAL=13";

const LEGACY = {
  kind: "legacy",
  summary: null,
  resultText: null,
  resultChars: null,
  truncated: false,
  errorMessage: null,
} as const;

const dbt = (overrides: Partial<DbtRunResult> = {}): DbtRunResult => ({
  kind: "dbt_run",
  summary: "dbt run · 12 ✓ 1 ✗ · 8.4 s",
  resultText: LOG,
  resultChars: LOG.length,
  truncated: false,
  errorMessage: null,
  command: "dbt run --select marts.revenue+",
  targetSchema: "analytics",
  sync: "pushed",
  exitCode: 1,
  statuses: { success: 12, error: 1 },
  total: 13,
  failures: [
    { node: "model.analytics.rpt_region_rollup", message: 'column "region_name" does not exist' },
  ],
  elapsedS: 8.4,
  log: LOG,
  logTruncated: false,
  ...overrides,
});

function step(overrides: Partial<RunStep> = {}): RunStep {
  return {
    key: "d1",
    sequence: 15,
    category: "dbt",
    status: "succeeded",
    title: "Ran dbt",
    tool: "dbt_execute",
    toolOrigin: "signalpilot",
    input: { command: "run", select: "marts.revenue+" },
    sql: null,
    code: null,
    file: null,
    sources: [],
    detail: null,
    result: null,
    startedAt: "2026-09-01T12:00:00.000Z",
    endedAt: "2026-09-01T12:00:08.400Z",
    durationMs: 8_400,
    children: [],
    subagentType: null,
    report: null,
    liveText: "",
    ...overrides,
  };
}

const q = (root: ParentNode, selector: string) => root.querySelector(selector);

describe("summarizeDbtRun", () => {
  it("folds statuses into the four buckets", () => {
    expect(
      tallyStatuses({ success: 3, pass: 2, warn: 1, fail: 1, "runtime error": 1, skipped: 4 }),
    ).toEqual({ pass: 5, warn: 1, error: 2, skip: 4 });
  });
  it("formats the stat and flags errors", () => {
    expect(summarizeDbtRun(step({ result: dbt() }))).toEqual({
      title: "dbt run",
      stat: "12 ✓ 1 ✗ · 8.4 s",
      ok: false,
    });
    expect(
      summarizeDbtRun(
        step({
          result: dbt({ statuses: { success: 5, warn: 2, skip: 1 }, exitCode: 0, failures: [] }),
        }),
      ),
    ).toEqual({ title: "dbt run", stat: "5 ✓ 0 ✗ · 2 ⚠ · 1 skip · 8.4 s", ok: true });
    expect(
      summarizeDbtRun(step({ result: dbt({ statuses: {}, exitCode: 2, elapsedS: null }) })).stat,
    ).toBe("exit 2");
    expect(summarizeDbtRun(step({ input: { command: "build" } })).title).toBe("dbt build");
  });
  it("stays open after completion only when something errored", () => {
    const def = getToolCardDefinition("dbt_run")!;
    expect(def.stayOpenOnComplete?.(step({ result: dbt() }), false)).toBe(true);
    expect(
      def.stayOpenOnComplete?.(step({ result: dbt({ statuses: { success: 13 } }) }), false),
    ).toBe(false);
  });
});

describe("dbt run card", () => {
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

  it("shows the command line and progress detail while running", async () => {
    await render(
      step({
        status: "running",
        endedAt: null,
        durationMs: null,
        detail: "dbt: 7 of 13 fct_orders",
      }),
    );
    const body = q(container, '[data-testid="chat-dbt-run-card"]');
    expect(body?.textContent).toContain("$dbt run --select marts.revenue+");
    expect(body?.textContent).toContain("dbt: 7 of 13 fct_orders");
  });

  it("stays expanded with tallies, bar, failures and the log when a model errored", async () => {
    await render(step({ result: dbt() }));
    expect(q(container, '[data-testid="chat-tool-card"]')?.getAttribute("data-density")).toBe(
      "expanded",
    );
    expect(q(container, '[data-testid="chat-dbt-run-tallies"]')?.textContent).toContain("Pass12");
    expect(q(container, ".chat-tool-bar-grow")).not.toBeNull();
    const failures = q(container, '[data-testid="chat-dbt-run-failures"]');
    expect(failures?.textContent).toContain("model.analytics.rpt_region_rollup");
    expect(failures?.textContent).toContain("region_name");
    expect(container.textContent).toContain("target analytics · sync pushed · exit 1");
    // Errors open the log by default.
    expect(
      q(container, '[data-testid="chat-dbt-run-log-toggle"]')?.getAttribute("aria-expanded"),
    ).toBe("true");
    expect(container.textContent).toContain("PASS=12");
  });

  it("compacts a clean run to a chip with the stat", async () => {
    await render(step({ result: dbt({ statuses: { success: 13 }, exitCode: 0, failures: [] }) }));
    const chip = q(container, '[data-testid="chat-tool-chip"]') as HTMLButtonElement;
    expect(chip.textContent).toContain("13 ✓ 0 ✗ · 8.4 s");
    await act(async () => chip.click());
    expect(q(container, '[data-testid="chat-dbt-run-failures"]')).toBeNull();
    const toggle = q(container, '[data-testid="chat-dbt-run-log-toggle"]') as HTMLButtonElement;
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    await act(async () => toggle.click());
    expect(container.textContent).toContain("Running with dbt=1.9.1");
  });

  it("degrades a legacy completion to the command line", async () => {
    await render(step({ result: LEGACY }));
    const chip = q(container, '[data-testid="chat-tool-chip"]') as HTMLButtonElement;
    expect(chip.textContent).toContain("dbt run");
    await act(async () => chip.click());
    expect(q(container, '[data-testid="chat-dbt-run-tallies"]')).toBeNull();
    expect(container.textContent).toContain("dbt run --select marts.revenue+");
  });
});
