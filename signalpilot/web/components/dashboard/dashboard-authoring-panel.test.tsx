import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { requestMock, routerPush } = vi.hoisted(() => ({
  requestMock: vi.fn(),
  routerPush: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: routerPush }),
}));

vi.mock("~/lib/api", () => ({
  request: requestMock,
}));

import {
  DashboardAuthoringPanel,
  dashboardAuthoringErrorMessage,
  dashboardRepairPrompt,
} from "~/components/dashboard/dashboard-authoring-panel";

describe("DashboardAuthoringPanel", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    requestMock.mockReset();
    routerPush.mockReset();
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    document.body.replaceChildren();
  });

  it("opens the dashboard preview in its original Data Chat thread", async () => {
    await act(async () => {
      root.render(<DashboardAuthoringPanel dashboardId="dashboard-1" />);
    });
    const launcher = container.querySelector("button");
    requestMock.mockResolvedValueOnce({
      conversation_id: "conversation-1",
      authoring_session_id: "session-1",
    });
    await act(async () => {
      launcher?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(requestMock).toHaveBeenCalledWith(
      "/api/dashboards/dashboard-1/authoring-chat",
      { method: "POST" },
    );
    expect(routerPush).toHaveBeenCalledWith(
      "/chats/conversation-1?dashboard=session-1",
    );
  });

  it("opens repair authoring with every chart error ready to submit", async () => {
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

    requestMock.mockResolvedValueOnce({
      conversation_id: "conversation-1",
      authoring_session_id: "session-1",
    });
    await act(async () => launcher?.click());

    const destination = routerPush.mock.calls[0]?.[0] as string;
    expect(destination).toContain("/chats/conversation-1?dashboard=session-1");
    const prompt = new URL(
      destination,
      "http://signalpilot.local",
    ).searchParams.get("prompt");
    expect(prompt).toBe(dashboardRepairPrompt(repairIssues));
    expect(prompt).toContain("Revenue Trend");
    expect(prompt).toContain("Gross Profit Trend");
  });
});

describe("dashboardAuthoringErrorMessage", () => {
  it("shows a safe API detail without the raw response envelope", () => {
    expect(
      dashboardAuthoringErrorMessage(
        new Error(
          '502: {"detail":"Dashboard authoring could not complete because Anthropic rejected the request."}',
        ),
      ),
    ).toBe(
      "Dashboard authoring could not complete because Anthropic rejected the request.",
    );
  });

  it("does not expose an unstructured server response", () => {
    expect(
      dashboardAuthoringErrorMessage(
        new Error("500: provider response contained internal details"),
      ),
    ).toBe("The dashboard draft could not be updated. Please try again.");
  });
});
