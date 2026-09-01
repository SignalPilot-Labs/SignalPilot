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
