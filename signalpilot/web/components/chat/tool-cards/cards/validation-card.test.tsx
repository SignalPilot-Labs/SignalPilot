import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { RunStep, ValidationResult } from "~/lib/chat-run-steps";
import { ToolCard } from "../tool-card";
import { looksLikeSql, summarizeValidation } from "./validation-card";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const SQL =
  "select o.order_id, region_name from analytics.fct_orders o where o.quarter = '2025-Q3'";
const MESSAGE = 'column "region_name" does not exist on analytics.fct_orders';

const LEGACY = {
  kind: "legacy",
  summary: null,
  resultText: null,
  resultChars: null,
  truncated: false,
  errorMessage: null,
} as const;

const validation = (overrides: Partial<ValidationResult> = {}): ValidationResult => ({
  kind: "validation",
  summary: "valid",
  resultText: "VALID ✓\nEstimated rows: 12000",
  resultChars: 30,
  truncated: false,
  errorMessage: null,
  valid: true,
  estimatedRows: 12_000,
  expensive: false,
  message: null,
  suggestedFix: null,
  checks: ["syntax", "column references"],
  ...overrides,
});

function step(overrides: Partial<RunStep> = {}): RunStep {
  return {
    key: "v1",
    sequence: 3,
    category: "sql",
    status: "succeeded",
    title: "Validated the query",
    tool: "validate_sql",
    toolOrigin: "signalpilot",
    input: { sql: SQL },
    sql: SQL,
    code: null,
    file: null,
    sources: [],
    detail: null,
    result: null,
    startedAt: "2026-09-01T12:00:00.000Z",
    endedAt: "2026-09-01T12:00:00.400Z",
    durationMs: 400,
    children: [],
    subagentType: null,
    report: null,
    liveText: "",
    ...overrides,
  };
}

const q = (root: ParentNode, selector: string) => root.querySelector(selector);

describe("summarizeValidation", () => {
  it("keeps the humanized step title and reports valid with rows and expense", () => {
    expect(summarizeValidation(step({ result: validation() }))).toEqual({
      title: "Validated the query",
      stat: "valid · ~12,000 rows",
      ok: true,
    });
    expect(
      summarizeValidation(
        step({ tool: "analyze_grain", result: validation({ expensive: true, estimatedRows: null }) }),
      ).stat,
    ).toBe("valid · expensive");
    expect(
      summarizeValidation(step({ tool: "explain_query", title: "Explained the query plan" })).title,
    ).toBe("Explained the query plan");
  });
  it("falls back to a per-tool title only when the step has none", () => {
    expect(summarizeValidation(step({ tool: "explain_query", title: "" })).title).toBe("Query plan");
    expect(summarizeValidation(step({ tool: "check_model_schema", title: "" })).title).toBe(
      "Schema check",
    );
    expect(summarizeValidation(step({ tool: "verify_model_values", title: "" })).title).toBe(
      "Value check",
    );
    expect(summarizeValidation(step({ tool: "unknown_tool", title: "" })).title).toBe("Validation");
  });
  it("is not ok when invalid or failed", () => {
    expect(
      summarizeValidation(step({ result: validation({ valid: false, estimatedRows: null }) })),
    ).toMatchObject({ stat: "invalid", ok: false });
    expect(summarizeValidation(step({ status: "failed" })).ok).toBe(false);
  });
  it("detects SQL-looking fixes", () => {
    expect(looksLikeSql("select 1")).toBe(true);
    expect(looksLikeSql("Join dim_regions on region_id")).toBe(true);
    expect(looksLikeSql("Use the region dimension instead")).toBe(false);
  });
});

describe("validation card", () => {
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

  it("shows the SQL and a validating rail while running", async () => {
    await render(step({ status: "running", endedAt: null, durationMs: null }));
    const body = q(container, '[data-testid="chat-validation-card"]');
    expect(q(container, '[data-testid="chat-tool-card-validation"]')).not.toBeNull();
    expect(body?.textContent).toContain("Validating…");
    const sql = q(body!, '[data-testid="chat-validation-sql"]');
    expect(sql?.textContent).toContain("order_id");
    // Folded to four lines while running; the FROM clause waits behind the toggle.
    expect(sql?.textContent).toContain("more lines");
    expect(sql?.textContent).not.toContain("fct_orders");
  });

  it("mounts a valid completion as a chip and expands to the headline", async () => {
    await render(step({ result: validation() }));
    const chip = q(container, '[data-testid="chat-tool-chip"]') as HTMLButtonElement;
    expect(chip.textContent).toContain("Validated the query");
    expect(chip.textContent).toContain("valid · ~12,000 rows");
    await act(async () => chip.click());
    expect(q(container, '[data-testid="chat-validation-verdict"]')?.textContent).toContain("Valid");
    expect(q(container, ".chat-boot-check")).not.toBeNull();
    expect(q(container, '[data-testid="chat-validation-checks"]')?.textContent).toContain(
      "column references",
    );
    expect(q(container, '[data-testid="chat-validation-sql"]')).not.toBeNull();
  });

  it("keeps a failed check open with the X mark, message and SQL fix", async () => {
    await render(
      step({
        status: "failed",
        detail: MESSAGE,
        result: validation({
          valid: false,
          estimatedRows: null,
          message: MESSAGE,
          errorMessage: MESSAGE,
          suggestedFix: "join analytics.dim_regions r on r.region_id = o.region_id",
        }),
      }),
    );
    expect(q(container, '[data-testid="chat-tool-card"]')?.getAttribute("data-density")).toBe(
      "expanded",
    );
    expect(q(container, '[data-testid="chat-validation-verdict"]')?.textContent).toContain(
      "Invalid",
    );
    expect(q(container, ".chat-boot-check")).toBeNull();
    expect(container.textContent).toContain(MESSAGE);
    const fix = q(container, '[data-testid="chat-validation-fix"]');
    expect(fix?.textContent).toContain("Suggested fix");
    expect(fix?.querySelector("pre")?.textContent).toContain("dim_regions");
    expect(q(container, '[data-testid="chat-tool-error"]')).not.toBeNull();
    // The banner owns the message; the headline does not repeat it.
    expect(container.textContent?.split(MESSAGE)).toHaveLength(2);
    expect(q(container, '[data-testid="chat-validation-verdict"] + p')).toBeNull();
  });

  it("shows the message in the headline when the step did not fail", async () => {
    await render(step({ result: validation({ valid: false, estimatedRows: null, message: MESSAGE }) }));
    await act(async () => (q(container, '[data-testid="chat-tool-chip"]') as HTMLButtonElement).click());
    expect(q(container, '[data-testid="chat-validation-verdict"] + p')?.textContent).toBe(MESSAGE);
    expect(q(container, '[data-testid="chat-tool-error"]')).toBeNull();
  });

  it("drops a failed step's message when the banner carries a different error", async () => {
    await render(
      step({
        status: "failed",
        detail: "validate_sql raised",
        result: validation({
          valid: false,
          estimatedRows: null,
          message: MESSAGE,
          errorMessage: "validate_sql raised",
        }),
      }),
    );
    expect(q(container, '[data-testid="chat-validation-verdict"] + p')).toBeNull();
    expect(q(container, '[data-testid="chat-tool-error"]')?.textContent).toContain("validate_sql raised");
  });

  it("degrades a legacy completion to the SQL input only", async () => {
    await render(step({ result: LEGACY }));
    const chip = q(container, '[data-testid="chat-tool-chip"]') as HTMLButtonElement;
    expect(chip.textContent).toContain("Validated the query");
    await act(async () => chip.click());
    expect(q(container, '[data-testid="chat-validation-verdict"]')).toBeNull();
    const sql = q(container, '[data-testid="chat-validation-sql"]');
    expect(sql?.textContent).toContain("order_id");
    await act(async () => (sql?.querySelector("button") as HTMLButtonElement).click());
    expect(sql?.textContent).toContain("fct_orders");
  });
});
