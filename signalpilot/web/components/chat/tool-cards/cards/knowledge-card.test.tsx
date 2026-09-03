import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { KnowledgeResult, RunStep } from "~/lib/chat-run-steps";
import { ToolCard } from "../tool-card";
import { summarizeKnowledge } from "./knowledge-card";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const QUERY = "net revenue region definition";
const DOCS: KnowledgeResult["docs"] = [
  {
    id: "kb-114",
    scope: "org",
    category: "definitions",
    title: "Net revenue",
    snippet: "Gross revenue minus discounts and refunds issued before quarter close.",
  },
  {
    id: "kb-207",
    scope: "project",
    category: "conventions",
    title: "Region dimension join",
    snippet: "Always join analytics.dim_regions on region_id.",
  },
  {
    id: "kb-311",
    scope: "connection",
    category: "caveats",
    title: "APAC marketplace launches",
    snippet: null,
  },
];

const LEGACY = {
  kind: "legacy",
  summary: null,
  resultText: null,
  resultChars: null,
  truncated: false,
  errorMessage: null,
} as const;

const knowledge = (overrides: Partial<KnowledgeResult> = {}): KnowledgeResult => ({
  kind: "knowledge",
  summary: "3 knowledge docs",
  resultText: "…",
  resultChars: 1,
  truncated: false,
  errorMessage: null,
  mode: "search",
  query: QUERY,
  docs: DOCS,
  total: 3,
  docsTruncated: false,
  ...overrides,
});

function step(overrides: Partial<RunStep> = {}): RunStep {
  return {
    key: "k1",
    sequence: 16,
    category: "source",
    status: "succeeded",
    title: "Searched knowledge",
    tool: "search_knowledge",
    toolOrigin: "signalpilot",
    input: { query: QUERY },
    sql: null,
    code: null,
    file: null,
    sources: [],
    detail: null,
    result: null,
    startedAt: "2026-09-01T12:00:00.000Z",
    endedAt: "2026-09-01T12:00:00.250Z",
    durationMs: 250,
    children: [],
    subagentType: null,
    report: null,
    liveText: "",
    ...overrides,
  };
}

const q = (root: ParentNode, selector: string) => root.querySelector(selector);

describe("summarizeKnowledge", () => {
  it("counts docs and quotes the query", () => {
    expect(summarizeKnowledge(step({ result: knowledge() }))).toEqual({
      title: "Searched knowledge",
      stat: `3 docs for "${QUERY}"`,
      ok: true,
    });
    expect(
      summarizeKnowledge(
        step({
          tool: "get_knowledge",
          input: { ids: ["kb-1"] },
          result: knowledge({ mode: "get", query: null, docs: [DOCS[0]], total: 1 }),
        }),
      ),
    ).toEqual({ title: "Knowledge", stat: "1 doc", ok: true });
  });
  it("has no stat without a result and is not ok when failed", () => {
    expect(summarizeKnowledge(step())).toEqual({
      title: "Searched knowledge",
      stat: null,
      ok: true,
    });
    expect(summarizeKnowledge(step({ status: "failed" })).ok).toBe(false);
  });
});

describe("knowledge card", () => {
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

  it("shows the query pill and ghost lines while running", async () => {
    await render(step({ status: "running", endedAt: null, durationMs: null }));
    const body = q(container, '[data-testid="chat-knowledge-card"]');
    expect(body?.textContent).toContain(QUERY);
    expect(body?.querySelectorAll(".animate-shimmer").length).toBe(3);
    expect(body?.textContent).toContain("Searching knowledge…");
  });

  it("compacts to a chip and expands to the doc list", async () => {
    await render(step({ result: knowledge() }));
    const chip = q(container, '[data-testid="chat-tool-chip"]') as HTMLButtonElement;
    expect(chip.textContent).toContain("3 docs");
    await act(async () => chip.click());
    const docs = container.querySelectorAll('[data-testid="chat-knowledge-doc"]');
    expect(docs.length).toBe(3);
    expect(docs[0].textContent).toContain("Net revenue");
    expect(docs[0].textContent).toContain("org");
    expect(docs[0].textContent).toContain("definitions");
    expect(docs[0].textContent).toContain("kb-114");
    expect(docs[0].querySelector(".line-clamp-2")?.textContent).toContain("Gross revenue");
    expect(docs[2].querySelector(".line-clamp-2")).toBeNull();
    expect(container.textContent).not.toContain("more");
  });

  it("notes the hidden docs when the list was capped", async () => {
    await render(step({ result: knowledge({ total: 12, docsTruncated: true }) }));
    const chip = q(container, '[data-testid="chat-tool-chip"]') as HTMLButtonElement;
    expect(chip.textContent).toContain("12 docs");
    await act(async () => chip.click());
    expect(container.textContent).toContain("+9 more");
  });

  it("degrades a legacy completion to the query pill", async () => {
    await render(step({ result: LEGACY }));
    const chip = q(container, '[data-testid="chat-tool-chip"]') as HTMLButtonElement;
    await act(async () => chip.click());
    expect(container.querySelectorAll('[data-testid="chat-knowledge-doc"]').length).toBe(0);
    expect(q(container, '[data-testid="chat-knowledge-card"]')?.textContent).toContain(QUERY);
  });
});
