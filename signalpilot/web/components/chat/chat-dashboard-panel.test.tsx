import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SWRConfig } from "swr";

import fiveComponents from "~/dashboard/lightdash-contract/fixtures/five-components.json";
import { fromLightdashFixture } from "~/dashboard/lightdash-contract";

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }));

vi.mock("~/lib/api", () => ({ request: requestMock }));
vi.mock("~/components/dashboard/dashboard-runtime-provider", () => ({
  DashboardRuntimeProvider: ({
    definition,
  }: {
    definition: { name: string };
  }) => <div data-testid="dashboard-runtime">{definition.name}</div>,
}));

import { ChatDashboardPanel } from "~/components/chat/chat-dashboard-panel";
import type { DashboardAuthoringSession } from "~/components/dashboard/dashboard-authoring-panel";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

function dashboardSession(): DashboardAuthoringSession {
  return {
    id: "session-live",
    thread_id: "thread-1",
    conversation_id: "conversation-1",
    dashboard_id: null,
    base_version_id: null,
    applied_version_id: null,
    definition: fromLightdashFixture(fiveComponents),
    operations: [],
    summary: "Created a dashboard.",
    status: "preview",
    requires_custom_sql_confirmation: false,
    custom_sql_confirmed: false,
    custom_sql_chart_ids: [],
    draft_revision: 1,
    events: [],
  };
}

function partialDashboardSession(): DashboardAuthoringSession {
  const definition = fromLightdashFixture(fiveComponents);
  return {
    ...dashboardSession(),
    definition: {
      ...definition,
      charts: [definition.charts[0]],
      tiles: [definition.tiles[0]],
    },
    status: "partial_failed",
    expected_chart_count: 2,
    plan: {
      name: definition.name,
      timezone: "UTC",
      intents: [
        {
          chart_id: definition.charts[0].id,
          tile_id: definition.tiles[0].uuid,
          label: definition.charts[0].title,
          section: "Overview",
          order: 0,
          layout: { x: 0, y: 0, w: 18, h: 6 },
          visualization: "kpi",
        },
        {
          chart_id: "chart-failed",
          tile_id: "tile-failed",
          label: "Failed revenue chart",
          section: "Overview",
          order: 1,
          layout: { x: 18, y: 0, w: 18, h: 6 },
          visualization: "bar",
        },
      ],
    },
    chart_drafts: [
      {
        chart_id: definition.charts[0].id,
        ordinal: 0,
        status: "ready",
        attempt_count: 1,
        safe_error: null,
      },
      {
        chart_id: "chart-failed",
        ordinal: 1,
        status: "failed",
        attempt_count: 2,
        safe_error: "This chart could not be validated.",
      },
    ],
  };
}

describe("Chat dashboard live preview", () => {
  let container: HTMLDivElement;
  let root: Root;
  let stylesLoaded: boolean;

  beforeEach(() => {
    requestMock.mockReset();
    stylesLoaded = true;
    vi.spyOn(window, "getComputedStyle").mockImplementation(
      () =>
        ({
          getPropertyValue: (property: string) =>
            property === "--dashboard-runtime-styles-ready" && stylesLoaded
              ? "1"
              : "",
        }) as CSSStyleDeclaration,
    );
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.restoreAllMocks();
  });

  it("keeps the validated draft visible and locked until the revision refetches", async () => {
    requestMock.mockResolvedValue(dashboardSession());

    const renderPanel = (updateLabel: string | null) => (
      <SWRConfig
        value={{ provider: () => new Map(), dedupingInterval: 0 }}
      >
        <ChatDashboardPanel
          sessionId="session-live"
          updateLabel={updateLabel}
          onClose={vi.fn()}
        />
      </SWRConfig>
    );

    await act(async () => root.render(renderPanel("Validating chart fields")));
    await vi.waitFor(() => {
      expect(container.querySelector('[role="status"]')?.textContent).toContain(
        "Validating chart fields",
      );
      expect(
        container.querySelector('[data-testid="dashboard-runtime"]'),
      ).not.toBeNull();
    });

    const button = (label: string) =>
      [...container.querySelectorAll("button")].find(
        (candidate) => candidate.textContent?.trim() === label,
      ) as HTMLButtonElement | undefined;
    expect(button("Apply")?.disabled).toBe(true);
    expect(button("Discard")?.disabled).toBe(true);

    await act(async () => root.render(renderPanel(null)));
    await vi.waitFor(() => {
      expect(container.querySelector('[role="status"]')).toBeNull();
      expect(button("Discard")?.disabled).toBe(false);
      expect(button("Apply")?.disabled).toBe(true);
    });
    expect(requestMock).toHaveBeenCalledWith(
      "/api/dashboard-authoring/sessions/session-live",
    );
  });

  it("never exposes the dashboard DOM before its CSS module is applied", async () => {
    stylesLoaded = false;
    requestMock.mockResolvedValue(dashboardSession());

    await act(async () => {
      root.render(
        <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
          <ChatDashboardPanel
            sessionId="session-live"
            onClose={vi.fn()}
          />
        </SWRConfig>,
      );
    });
    await vi.waitFor(() => {
      expect(
        container.querySelector(
          '[data-testid="dashboard-preview-style-loading"]',
        ),
      ).not.toBeNull();
    });

    const stage = container.querySelector(
      '[data-testid="dashboard-preview-runtime-stage"]',
    ) as HTMLDivElement;
    expect(stage.style.visibility).toBe("hidden");
    expect(stage.getAttribute("aria-hidden")).toBe("true");

    stylesLoaded = true;
    await act(
      () => new Promise((resolve) => window.setTimeout(resolve, 60)),
    );
    await vi.waitFor(() => {
      expect(
        container.querySelector(
          '[data-testid="dashboard-preview-style-loading"]',
        ),
      ).toBeNull();
    });
    expect(stage.style.visibility).toBe("visible");
    expect(stage.getAttribute("aria-hidden")).toBe("false");
  });

  it("keeps ready charts visible and exposes every safe failed-chart detail", async () => {
    requestMock.mockResolvedValue(partialDashboardSession());

    await act(async () => {
      root.render(
        <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
          <ChatDashboardPanel
            sessionId="session-live"
            updateRevision={3}
            onClose={vi.fn()}
          />
        </SWRConfig>,
      );
    });

    await vi.waitFor(() => {
      expect(
        container.querySelector('[data-testid="dashboard-runtime"]'),
      ).not.toBeNull();
      expect(
        container.querySelector(
          '[data-testid="dashboard-chart-placeholder-chart-failed"]',
        ),
      ).not.toBeNull();
    });
    const failed = container.querySelector(
      '[data-testid="dashboard-chart-placeholder-chart-failed"]',
    );
    expect(failed?.getAttribute("title")).toBe(
      "This chart could not be validated.",
    );
    expect(container.textContent).toContain("1/2 ready");
    expect(container.textContent).toContain("Retry failed charts");
  });
});
