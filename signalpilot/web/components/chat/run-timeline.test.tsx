import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { ActivityGroup } from "~/components/chat/run-timeline";
import type { RunStep } from "~/lib/chat-run-steps";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const baseStep = (status: RunStep["status"]): RunStep => ({
  key: "base-step",
  sequence: 1,
  category: "generic",
  status,
  title: "Ran a tool",
  tool: "generic_tool",
  toolOrigin: "chat",
  input: {},
  sql: null,
  code: null,
  file: null,
  sources: [],
  detail: null,
  result: null,
  startedAt: "2026-09-01T12:00:00.000Z",
  endedAt: status === "running" ? null : "2026-09-01T12:00:02.000Z",
  durationMs: status === "running" ? null : 2_000,
  children: [],
  subagentType: null,
  report: null,
  liveText: "",
});

const queryStep = (key: string, summary: string): RunStep => ({
  ...baseStep("succeeded"),
  key,
  category: "sql",
  title: "Queried the warehouse",
  tool: "query_database",
  toolOrigin: "signalpilot",
  input: { sql: "select 1" },
  sql: "select 1",
  detail: summary,
  result: {
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
  },
});

describe("completed activity group header", () => {
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

  it("collapses to a merged chip strip with the screen-reader tally", async () => {
    const steps = [
      queryStep("q1", "1,204 rows · 312 ms"),
      queryStep("q2", "1,206 rows · 90 ms"),
    ];
    await act(async () => {
      root.render(<ActivityGroup steps={steps} live={false} />);
    });
    const group = container.querySelector('[data-testid="chat-activity-group"]');
    expect(group?.textContent).toContain("Worked through 2 steps · 2 queries");
    expect(group?.querySelector(".sr-only")?.textContent).toBe(
      "Worked through 2 steps · 2 queries",
    );
    const chips = group?.querySelectorAll('[data-testid="chat-tool-chip"]') ?? [];
    // Strip chip (merged) + two compact card chips inside the folded timeline.
    const strip = group?.querySelector('[data-testid="chat-tool-chip-strip"]');
    expect(strip?.querySelectorAll('[data-testid="chat-tool-chip"]')).toHaveLength(1);
    expect(strip?.textContent).toContain("2 queries");
    expect(strip?.textContent).toContain("2,410 rows");
    expect(chips.length).toBeGreaterThan(1);
    // The header toggle is the first button and starts closed.
    expect(group?.querySelector("button")?.getAttribute("aria-expanded")).toBe("false");
    // Picking the chip opens the group and expands the first merged card.
    await act(async () => {
      (strip?.querySelector("button") as HTMLButtonElement).click();
    });
    expect(group?.querySelector("button")?.getAttribute("aria-expanded")).toBe("true");
    const cards = group?.querySelectorAll('[data-testid="chat-tool-card"]') ?? [];
    expect(cards[0]?.getAttribute("data-density")).toBe("expanded");
    expect(cards[1]?.getAttribute("data-density")).toBe("compact");
  });

  it("leaves a completed group closed with every card compact", async () => {
    const steps = [queryStep("q1", "3 rows"), queryStep("q2", "9 rows")];
    await act(async () => {
      root.render(<ActivityGroup steps={steps} live={false} />);
    });
    const group = container.querySelector('[data-testid="chat-activity-group"]');
    expect(group?.querySelector("button")?.getAttribute("aria-expanded")).toBe("false");
    const cards = group?.querySelectorAll('[data-testid="chat-tool-card"]') ?? [];
    for (const card of cards) expect(card.getAttribute("data-density")).toBe("compact");
  });
});

describe("live group window", () => {
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

  it("shows the latest three one-line rows and folds older ones", async () => {
    const steps = Array.from({ length: 5 }, (_, index) => ({
      ...queryStep(`q${index}`, `${index} rows`),
      sequence: index + 1,
      status: index === 4 ? ("running" as const) : ("succeeded" as const),
    }));
    await act(async () => {
      root.render(<ActivityGroup steps={steps} live />);
    });
    expect(container.querySelectorAll('[data-testid="chat-tool-card"]')).toHaveLength(3);
    const earlier = container.querySelector(
      '[data-testid="chat-timeline-earlier"]',
    ) as HTMLButtonElement;
    expect(earlier.textContent).toBe("+2 earlier steps");
    // Nothing is expanded while the chain runs.
    for (const card of container.querySelectorAll('[data-testid="chat-tool-card"]')) {
      expect(card.getAttribute("data-density")).not.toBe("expanded");
    }
    await act(async () => earlier.click());
    expect(container.querySelectorAll('[data-testid="chat-tool-card"]')).toHaveLength(5);
  });
});
