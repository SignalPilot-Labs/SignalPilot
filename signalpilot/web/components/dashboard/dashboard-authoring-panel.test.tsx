import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import fiveComponents from "~/dashboard/lightdash-contract/fixtures/five-components.json";
import { fromLightdashFixture } from "~/dashboard/lightdash-contract";
import styles from "~/components/dashboard/dashboard-runtime.module.css";

vi.mock("~/components/dashboard/dashboard-runtime-provider", () => ({
  DashboardRuntimeProvider: ({
    definition,
  }: {
    definition: { name: string };
  }) => (
    <div data-testid="governed-preview">
      {definition.name}
      <button data-testid="preview-control" type="button">
        Preview control
      </button>
    </div>
  ),
}));

vi.mock("~/lib/api", () => ({
  request: vi.fn(() => new Promise(() => undefined)),
}));

import {
  DashboardAuthoringPanel,
  DashboardAuthoringWorkspace,
  dashboardRepairPrompt,
  type DashboardAuthoringSession,
} from "~/components/dashboard/dashboard-authoring-panel";

describe("DashboardAuthoringWorkspace", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    document.body.replaceChildren();
  });

  it("keeps the durable transcript beside the current draft and gates custom SQL", async () => {
    const definition = fromLightdashFixture(fiveComponents);
    const session: DashboardAuthoringSession = {
      id: "session-1",
      thread_id: "thread-1",
      dashboard_id: "dashboard-1",
      base_version_id: "version-1",
      definition,
      operations: [],
      summary: "Updated one chart.",
      status: "preview",
      requires_custom_sql_confirmation: true,
      custom_sql_confirmed: false,
      custom_sql_chart_ids: ["chart-sql"],
      draft_revision: 2,
      events: [
        {
          id: "event-1",
          sequence: 1,
          kind: "user",
          status: "info",
          message: "Make revenue a line chart",
          metadata: {},
        },
        {
          id: "event-2",
          sequence: 2,
          kind: "assistant",
          status: "success",
          message: "Updated one chart.",
          metadata: {},
        },
      ],
    };
    await act(async () => {
      root.render(
        <DashboardAuthoringWorkspace
          dashboardId="dashboard-1"
          versionId="version-1"
          baseDefinition={definition}
          session={session}
          onSession={vi.fn()}
          onApplied={vi.fn()}
          onDiscard={vi.fn()}
        />,
      );
    });
    expect(container.textContent).toContain("Make revenue a line chart");
    expect(container.textContent).toContain("Updated one chart.");
    expect(container.textContent).toContain("Draft 2");
    expect(container.textContent).not.toContain("Governed authoring");
    expect(container.textContent).not.toContain("Live governed preview");
    expect(
      container.querySelector("[data-testid='governed-preview']")?.textContent,
    ).toContain(definition.name);
    const apply = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent?.trim() === "Apply",
    );
    expect(apply?.disabled).toBe(true);
    expect(apply?.classList.contains(styles.authoringToolbarButton)).toBe(true);
    expect(
      container
        .querySelector("[data-testid='preview-control']")
        ?.classList.contains(styles.authoringToolbarButton),
    ).toBe(false);
    expect(container.textContent).toContain("chart-sql uses custom SQL");
    expect(
      container.querySelector("button[aria-pressed='true']")?.textContent,
    ).toBe("Chat");
    expect(container.querySelector("form textarea")?.id).toBe(
      "dashboard-authoring-prompt",
    );
  });

  it("mounts the edit overlay at the document root", async () => {
    const definition = fromLightdashFixture(fiveComponents);
    await act(async () => {
      root.render(
        <DashboardAuthoringPanel
          dashboardId="dashboard-1"
          versionId="version-1"
          baseDefinition={definition}
          onApplied={vi.fn()}
        />,
      );
    });
    const launcher = container.querySelector("button");
    await act(async () => {
      launcher?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    const overlay = document.querySelector(
      "[data-testid='dashboard-authoring-overlay']",
    );
    expect(overlay?.parentElement).toBe(document.body);
    expect(
      overlay?.querySelector("#dashboard-authoring-prompt"),
    ).not.toBeNull();
  });

  it("opens repair authoring with every chart error ready to submit", async () => {
    const definition = fromLightdashFixture(fiveComponents);
    const repairIssues = [
      {
        chartTitle: "Revenue Trend",
        message: "The returned data does not match the expected fields.",
      },
      {
        chartTitle: "Gross Profit Trend",
        message: "This chart query is no longer valid.",
      },
    ];
    await act(async () => {
      root.render(
        <DashboardAuthoringPanel
          dashboardId="dashboard-1"
          versionId="version-1"
          baseDefinition={definition}
          onApplied={vi.fn()}
          intent="repair"
          repairIssues={repairIssues}
        />,
      );
    });
    const launcher = container.querySelector("button");
    expect(launcher?.textContent).toContain("Repair");
    expect(launcher?.getAttribute("aria-label")).toBe(
      "Repair 2 failing charts with AI",
    );

    await act(async () => launcher?.click());

    const overlay = document.querySelector(
      "[data-testid='dashboard-authoring-overlay']",
    );
    const textarea = overlay?.querySelector<HTMLTextAreaElement>(
      "#dashboard-authoring-prompt",
    );
    expect(textarea?.value).toBe(dashboardRepairPrompt(repairIssues));
    expect(textarea?.value).toContain("Revenue Trend");
    expect(textarea?.value).toContain("Gross Profit Trend");
    expect(overlay?.textContent).toContain("Create repair preview");
    expect(overlay?.textContent).toContain(
      "the saved dashboard changes only after Apply",
    );
  });
});
