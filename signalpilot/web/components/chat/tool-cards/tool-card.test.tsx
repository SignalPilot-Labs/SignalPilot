import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { RunStep, ToolResult } from "~/lib/chat-run-steps";
import { resolveToolCard } from "./registry";
import { ToolCard } from "./tool-card";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const jsonResult = (value: unknown, summary = "Inspected 12 models"): ToolResult => ({
  kind: "json",
  summary,
  resultText: JSON.stringify(value),
  resultChars: JSON.stringify(value).length,
  truncated: false,
  errorMessage: null,
  value,
});

function step(overrides: Partial<RunStep> = {}): RunStep {
  return {
    key: "s1",
    sequence: 1,
    category: "dbt",
    status: "succeeded",
    title: "Inspected the dbt project",
    tool: "inspect_dbt",
    toolOrigin: "signalpilot",
    input: { project: "jaffle_shop", select: "marts.*" },
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

const q = (root: ParentNode, selector: string) => root.querySelector(selector);

describe("resolveToolCard", () => {
  it("keeps claude-code file/todo tools on the legacy row", () => {
    expect(
      resolveToolCard(step({ tool: "Write", toolOrigin: "claude-code", category: "file-write" })),
    ).toBeNull();
    expect(
      resolveToolCard(step({ tool: "TodoWrite", toolOrigin: "claude-code", category: "todo" })),
    ).toBeNull();
  });
  it("resolves Bash and MCP tools, re-keying the generic card to the real kind", () => {
    expect(
      resolveToolCard(step({ tool: "Bash", toolOrigin: "claude-code", category: "terminal" }))?.kind,
    ).toBe("terminal");
    expect(resolveToolCard(step({ tool: "query_database", category: "sql" }))?.kind).toBe("table");
    expect(resolveToolCard(step({ tool: "some_new_tool" }))?.kind).toBe("legacy");
    expect(resolveToolCard(step({ result: jsonResult({}) }))?.kind).toBe("json");
  });
  it("ignores non-tool steps", () => {
    expect(resolveToolCard(step({ tool: null }))).toBeNull();
    expect(resolveToolCard(step({ category: "subagent", tool: "Agent" }))).toBeNull();
  });
});

describe("ToolCard (generic)", () => {
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
  const render = async (s: RunStep, extra: Record<string, unknown> = {}) => {
    await act(async () => {
      root.render(
        <ol>
          <ToolCard step={s} groupLive isLastInGroup {...extra} />
        </ol>,
      );
    });
  };

  it("renders the running density with the input echo and a live rail", async () => {
    await render(step({ status: "running", endedAt: null, durationMs: null }));
    const card = q(container, '[data-testid="chat-tool-card"]');
    expect(card?.getAttribute("data-density")).toBe("running");
    expect(card?.getAttribute("data-kind")).toBe("json");
    expect(card?.getAttribute("data-tool")).toBe("inspect_dbt");
    expect(q(container, '[data-testid="chat-tool-card-json"]')).not.toBeNull();
    expect(card?.textContent).toContain("jaffle_shop");
    expect(card?.textContent).toContain("Working…");
  });

  it("mounts a completed step as a chip and expands to the JSON tree on click", async () => {
    await render(step({ result: jsonResult({ models: [{ name: "fct_orders" }], ok: true }) }));
    const card = q(container, '[data-testid="chat-tool-card"]');
    expect(card?.getAttribute("data-density")).toBe("compact");
    const chip = q(container, '[data-testid="chat-tool-chip"]') as HTMLButtonElement;
    expect(chip.getAttribute("data-kind")).toBe("json");
    expect(chip.textContent).toContain("Inspected the dbt project");
    expect(chip.textContent).toContain("Inspected 12 models");
    await act(async () => chip.click());
    expect(card?.getAttribute("data-density")).toBe("expanded");
    const tree = q(container, '[data-testid="chat-tool-json-tree"]');
    // Two levels open: the object inside the array is still folded.
    expect(tree?.textContent).toContain("models");
    expect(tree?.textContent).toContain("1 keys");
    expect(tree?.textContent).not.toContain("fct_orders");
    const folded = [...(tree?.querySelectorAll('button[aria-expanded="false"]') ?? [])];
    await act(async () => (folded[0] as HTMLButtonElement).click());
    expect(tree?.textContent).toContain("fct_orders");
    expect(q(container, '[data-testid="chat-tool-raw-toggle"]')).not.toBeNull();
  });

  it("keeps a failed step expanded with the error banner", async () => {
    await render(
      step({
        status: "failed",
        detail: "relation fct_orders does not exist",
        result: { ...jsonResult({}), errorMessage: "relation fct_orders does not exist" },
      }),
    );
    const card = q(container, '[data-testid="chat-tool-card"]');
    expect(card?.getAttribute("data-density")).toBe("expanded");
    expect(q(container, '[data-testid="chat-tool-error"]')?.textContent).toContain(
      "does not exist",
    );
  });

  it("opens a compact card when a focus request arrives", async () => {
    await render(step({ result: jsonResult({}) }));
    expect(q(container, '[data-testid="chat-tool-card"]')?.getAttribute("data-density")).toBe(
      "compact",
    );
    await render(step({ result: jsonResult({}) }), { focusRequested: 1 });
    expect(q(container, '[data-testid="chat-tool-card"]')?.getAttribute("data-density")).toBe(
      "expanded",
    );
  });
});
