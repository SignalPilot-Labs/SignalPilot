import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { ActivityGroup } from "~/components/chat/run-timeline";
import type { RunStep } from "~/lib/chat-run-steps";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const dashboardStep = (status: RunStep["status"]): RunStep => ({
  key: "dashboard-preview",
  sequence: 1,
  category: "dashboard",
  status,
  title: "Creating dashboard preview",
  tool: "create_dashboard_preview",
  toolOrigin: "chat",
  input: {
    request: "Create a revenue dashboard with margins and customer metrics.",
    timezone: "America/Sao_Paulo",
  },
  sql: null,
  code: null,
  file: null,
  sources: [],
  detail:
    status === "running"
      ? "Validating chart fields, filters, and bindings"
      : "Preview ready with 5 charts",
  result: null,
  startedAt: "2026-09-01T12:00:00.000Z",
  endedAt: status === "running" ? null : "2026-09-01T12:00:02.000Z",
  durationMs: status === "running" ? null : 2_000,
  children: [],
  subagentType: null,
  report: null,
  liveText: "",
});

describe("dashboard preview activity", () => {
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

  it("renders the live dashboard tool as one card without the generic timeline shells", async () => {
    await act(async () => {
      root.render(<ActivityGroup steps={[dashboardStep("running")]} live />);
    });

    const card = container.querySelector(
      '[data-testid="dashboard-preview-activity"]',
    );
    expect(card).not.toBeNull();
    expect(
      container.querySelector('[data-testid="chat-activity-group"]'),
    ).toBeNull();
    expect(
      container.querySelector('ol[aria-label="Agent activity"]'),
    ).toBeNull();
    expect(card?.textContent).toContain(
      "Validating chart fields, filters, and bindings",
    );
    expect(card?.textContent).toContain(
      "Create a revenue dashboard with margins and customer metrics.",
    );
    expect(card?.textContent?.match(/Dashboard preview/g)).toHaveLength(1);
    expect(card?.querySelector("button")?.getAttribute("aria-expanded")).toBe(
      "true",
    );
  });

  it("folds the same card down when the governed preview is ready", async () => {
    await act(async () => {
      root.render(
        <ActivityGroup steps={[dashboardStep("succeeded")]} live={false} />,
      );
    });

    const card = container.querySelector(
      '[data-testid="dashboard-preview-activity"]',
    );
    expect(card?.textContent).toContain("Governed preview ready for review");
    expect(card?.textContent).toContain("Ready");
    expect(card?.querySelector("button")?.getAttribute("aria-expanded")).toBe(
      "false",
    );
  });
});

const queryStep = (key: string, summary: string): RunStep => ({
  ...dashboardStep("succeeded"),
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

  it("pins the trailing table open in the final group of a completed run", async () => {
    const steps = [queryStep("q1", "3 rows"), queryStep("q2", "9 rows")];
    await act(async () => {
      root.render(<ActivityGroup steps={steps} live={false} isFinalGroup runCompleted />);
    });
    const group = container.querySelector('[data-testid="chat-activity-group"]');
    expect(group?.querySelector("button")?.getAttribute("aria-expanded")).toBe("true");
    const cards = group?.querySelectorAll('[data-testid="chat-tool-card"]') ?? [];
    expect(cards[0]?.getAttribute("data-density")).toBe("compact");
    expect(cards[1]?.getAttribute("data-density")).toBe("expanded");
  });
});
