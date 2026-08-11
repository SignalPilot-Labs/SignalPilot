import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { SWRConfig } from "swr";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  getChatLibrary: vi.fn(),
  getStandaloneArtifactObjectUrl: vi.fn(),
  promoteChatArtifact: vi.fn(),
  routerPush: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: mocks.routerPush,
    replace: vi.fn(),
  }),
  usePathname: () => "/reports",
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.ComponentProps<"a">) => (
    <a href={String(href)} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("~/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("~/lib/api")>();
  return {
    ...original,
    getChatLibrary: mocks.getChatLibrary,
    getStandaloneArtifactObjectUrl: mocks.getStandaloneArtifactObjectUrl,
    promoteChatArtifact: mocks.promoteChatArtifact,
  };
});

import { ChatReportLibrary } from "~/components/reports/chat-report-library";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

describe("ChatReportLibrary", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    mocks.getChatLibrary.mockResolvedValue({
      artifacts: {
        items: [
          {
            id: "artifact-1",
            kind: "table",
            filename: "revenue.csv",
            project_id: "project-1",
            project_name: "Revenue",
            original_thread_id: "conversation-1",
            original_thread_title: "Quarterly revenue",
            created_at: "2026-08-10T12:00:00Z",
            freshness_state: "unknown",
            freshness_at: "2026-08-10T11:00:00Z",
            freshness_checked_at: "2026-08-10T12:00:00Z",
            saved_report_id: null,
            saved_version_id: null,
            snapshot: {
              columns: [{ name: "revenue" }],
              rows: [{ revenue: 100 }],
            },
            download_formats: ["csv"],
          },
        ],
        next_cursor: null,
      },
      reports: {
        items: [
          {
            id: "report-1",
            report_id: "report-1",
            title: "Saved revenue",
            kind: "table",
            filename: "revenue.csv",
            is_shared: false,
            project_id: "project-1",
            project_name: "Revenue",
            original_thread_id: "conversation-1",
            original_thread_title: "Quarterly revenue",
            version_id: "version-1",
            version_ordinal: 1,
            freshness_state: "unknown",
            freshness_at: null,
            freshness_checked_at: "2026-08-10T12:00:00Z",
            updated_at: "2026-08-10T12:00:00Z",
            snapshot: {},
            download_url: "/api/chat/report-versions/version-1/download",
          },
        ],
        next_cursor: null,
      },
      facets: {
        artifact_types: ["table"],
        projects: [{ id: "project-1", name: "Revenue" }],
        original_threads: [
          { id: "conversation-1", title: "Quarterly revenue" },
        ],
      },
    });
    mocks.promoteChatArtifact.mockResolvedValue({
      status: "created",
      report_id: "report-new",
      version_id: "version-new",
    });
    mocks.getStandaloneArtifactObjectUrl.mockResolvedValue(
      "blob:runtime-chart",
    );
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: vi.fn(),
    });
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.clearAllMocks();
  });

  it("renders a reports-first split view and promotes from the selected artifact preview", async () => {
    await act(async () => {
      root.render(
        <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
          <ChatReportLibrary />
        </SWRConfig>,
      );
    });
    await vi.waitFor(() =>
      expect(container.textContent).toContain("Saved revenue"),
    );

    const tabs = [
      ...container.querySelectorAll<HTMLButtonElement>('[role="tab"]'),
    ];
    expect(
      tabs.map((tab) => tab.textContent?.replace(/\s+/g, " ").trim()),
    ).toEqual(["Reports1", "Artifacts1"]);
    expect(tabs[0].getAttribute("aria-selected")).toBe("true");
    expect(
      [...container.querySelectorAll("button")].some(
        (button) => button.textContent?.trim() === "Refresh data",
      ),
    ).toBe(false);
    expect(
      container.querySelector('aside button[aria-current="true"]')?.textContent,
    ).not.toContain("Unknown");
    expect(container.textContent).toContain("Saved revenue");
    expect(container.textContent).toContain("Quarterly revenue");
    expect(container.textContent).toContain("Open report");
    expect(container.textContent).not.toContain("Save as report");
    expect(container.querySelector("aside")?.textContent).not.toContain(
      "Original thread",
    );
    expect(container.querySelector("aside")?.textContent).not.toContain(
      "Open report",
    );
    expect(container.querySelector("section")?.textContent).toContain(
      "Original thread",
    );
    expect(container.querySelector("section")?.textContent).toContain(
      "Open report",
    );
    expect(
      container.querySelector('[aria-label="Search artifacts and reports"]'),
    ).not.toBeNull();
    expect(container.querySelector('[aria-label="Artifact type"]')).toBeNull();

    const filters = [...container.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Show filters"),
    );
    await act(async () => filters?.click());
    expect(container.textContent).toContain("Saved revenue");
    expect(
      container.querySelector('[aria-label="Artifact type"]'),
    ).not.toBeNull();
    expect(container.querySelector('[aria-label="Project"]')).not.toBeNull();
    expect(
      container.querySelector('[aria-label="Original thread"]'),
    ).not.toBeNull();
    expect(container.querySelector('[aria-label="Freshness"]')).not.toBeNull();
    expect(
      container.querySelector('[aria-label="Saved state"]'),
    ).not.toBeNull();
    expect(
      container.querySelector('[aria-label="Created date range"]'),
    ).not.toBeNull();
    expect(container.querySelectorAll('input[type="date"]')).toHaveLength(0);
    expect(
      container
        .querySelector('[aria-label="Open date range calendar"] svg')
        ?.getAttribute("class"),
    ).toContain("text-white");

    const artifactType = container.querySelector<HTMLSelectElement>(
      '[aria-label="Artifact type"]',
    );
    await act(async () => {
      if (!artifactType) return;
      artifactType.value = "table";
      artifactType.dispatchEvent(new Event("change", { bubbles: true }));
    });
    const clearFilters = await vi.waitFor(() => {
      const button = [
        ...container.querySelectorAll<HTMLButtonElement>("button"),
      ].find((candidate) => candidate.textContent?.trim() === "Clear filters");
      expect(button).not.toBeUndefined();
      return button;
    });
    await act(async () => clearFilters?.click());
    expect(
      container.querySelector<HTMLSelectElement>('[aria-label="Artifact type"]')
        ?.value,
    ).toBe("");

    await act(async () => tabs[1].click());
    await vi.waitFor(() =>
      expect(container.textContent).toContain("Save as report"),
    );
    expect(tabs[1].getAttribute("aria-selected")).toBe("true");
    expect(container.textContent).toContain("revenue.csv");
    const selectedRow = container.querySelector<HTMLButtonElement>(
      'aside button[aria-current="true"]',
    );
    expect(selectedRow?.textContent).not.toContain("Unknown");
    expect(selectedRow?.textContent).not.toContain("Checked");
    expect(selectedRow?.textContent).not.toContain("Created");
    expect(selectedRow?.textContent).toContain(
      new Date("2026-08-10T12:00:00Z").toLocaleDateString(),
    );
    expect(container.querySelector("aside")?.textContent).not.toContain(
      "Save as report",
    );
    expect(container.querySelector("section")?.textContent).toContain(
      "Save as report",
    );

    const save = [...container.querySelectorAll("button")].find(
      (button) => button.textContent?.trim() === "Save as report",
    );
    await act(async () => save?.click());
    expect(container.textContent).toContain(
      "Content and artifact type stay immutable",
    );

    const input = container.querySelector<HTMLInputElement>(
      'input[value="revenue"]',
    );
    expect(input).not.toBeNull();
    const submit = [...container.querySelectorAll("button")].find(
      (button) => button.textContent?.trim() === "Save report",
    );
    await act(async () => submit?.click());
    await vi.waitFor(() =>
      expect(mocks.promoteChatArtifact).toHaveBeenCalledWith(
        "artifact-1",
        "revenue",
      ),
    );
    expect(mocks.routerPush).toHaveBeenCalledWith("/reports/report-new");
  });

  it("loads runtime PNG previews and shows an explicit message when loading fails", async () => {
    const runtimeArtifact = (id: string, filename: string) => ({
      id,
      kind: "chart" as const,
      filename,
      project_id: "project-1",
      project_name: "Revenue",
      original_thread_id: "conversation-1",
      original_thread_title: "Pricing margins",
      created_at: "2026-08-10T12:00:00Z",
      freshness_state: "unknown" as const,
      freshness_at: null,
      freshness_checked_at: "2026-08-10T12:00:00Z",
      saved_report_id: null,
      saved_version_id: null,
      snapshot: { runtime_png: true, spec: {}, rows: [] },
      download_formats: ["png", "csv"],
    });
    mocks.getChatLibrary.mockResolvedValue({
      artifacts: {
        items: [
          runtimeArtifact("runtime-good", "pricing_margins_by_segment.png"),
          runtimeArtifact("runtime-bad", "broken_chart.png"),
        ],
        next_cursor: null,
      },
      reports: { items: [], next_cursor: null },
      facets: {
        artifact_types: ["chart"],
        projects: [{ id: "project-1", name: "Revenue" }],
        original_threads: [{ id: "conversation-1", title: "Pricing margins" }],
      },
    });
    mocks.getStandaloneArtifactObjectUrl.mockImplementation(
      async (artifactId: string) => {
        if (artifactId === "runtime-bad") throw new Error("preview failed");
        return "blob:pricing-chart";
      },
    );

    await act(async () => {
      root.render(
        <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
          <ChatReportLibrary />
        </SWRConfig>,
      );
    });
    await vi.waitFor(() =>
      expect(container.textContent).toContain("Artifacts2"),
    );
    const artifactsTab = [
      ...container.querySelectorAll<HTMLButtonElement>('[role="tab"]'),
    ].find((tab) => tab.textContent?.includes("Artifacts"));
    await act(async () => artifactsTab?.click());
    await vi.waitFor(() =>
      expect(
        container.querySelector<HTMLImageElement>(
          'img[alt="pricing_margins_by_segment.png"]',
        )?.src,
      ).toBe("blob:pricing-chart"),
    );
    expect(mocks.getStandaloneArtifactObjectUrl).toHaveBeenCalledWith(
      "runtime-good",
      "png",
    );

    const brokenItem = [
      ...container.querySelectorAll<HTMLButtonElement>("aside button"),
    ].find((button) => button.textContent?.includes("broken_chart.png"));
    await act(async () => brokenItem?.click());
    await vi.waitFor(() =>
      expect(container.textContent).toContain("Preview unavailable"),
    );
    expect(container.textContent).toContain(
      "Something unexpected happened while loading this preview",
    );
  });

  it("shows grouped artifact history and switches the displayed preview", async () => {
    const historyItem = (id: string, createdAt: string, revenue: number) => ({
      id,
      kind: "table" as const,
      filename: "revenue.csv",
      created_at: createdAt,
      freshness_state: "unknown" as const,
      freshness_at: null,
      freshness_checked_at: createdAt,
      saved_report_id: null,
      saved_version_id: null,
      snapshot: {
        columns: [{ name: "revenue" }],
        rows: [{ revenue }],
      },
      download_formats: ["csv"],
    });
    const newest = historyItem("artifact-newest", "2026-08-10T15:00:00Z", 200);
    const older = historyItem("artifact-older", "2026-08-09T15:00:00Z", 100);
    mocks.getChatLibrary.mockResolvedValue({
      artifacts: {
        items: [
          {
            ...newest,
            project_id: "project-1",
            project_name: "Revenue",
            original_thread_id: "conversation-1",
            original_thread_title: "Quarterly revenue",
            history: [newest, older],
          },
        ],
        next_cursor: null,
      },
      reports: { items: [], next_cursor: null },
      facets: {
        artifact_types: ["table"],
        projects: [{ id: "project-1", name: "Revenue" }],
        original_threads: [
          { id: "conversation-1", title: "Quarterly revenue" },
        ],
      },
    });

    await act(async () => {
      root.render(
        <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
          <ChatReportLibrary />
        </SWRConfig>,
      );
    });
    const artifactsTab = await vi.waitFor(() => {
      const tab = [
        ...container.querySelectorAll<HTMLButtonElement>('[role="tab"]'),
      ].find((candidate) => candidate.textContent?.includes("Artifacts1"));
      expect(tab).not.toBeUndefined();
      return tab;
    });
    await act(async () => artifactsTab?.click());

    const historyButton = await vi.waitFor(() => {
      const button = [...container.querySelectorAll("button")].find(
        (candidate) => candidate.textContent?.trim() === "History 2",
      );
      expect(button).not.toBeUndefined();
      return button;
    });
    expect(historyButton?.getAttribute("aria-haspopup")).toBe("dialog");
    expect(container.querySelector("section")?.textContent).toContain("200");

    const historyDialog = container.querySelector(
      '[aria-label="Artifact history"]',
    );
    expect(historyDialog?.textContent).toContain("newest first");
    const historyEntries = historyDialog?.querySelectorAll("button") || [];
    expect(historyEntries).toHaveLength(2);
    expect(historyEntries[0].getAttribute("aria-current")).toBe("true");
    expect(historyEntries[0].textContent).toContain("Showing");

    await act(async () => historyEntries[1]?.click());
    expect(historyEntries[1].getAttribute("aria-current")).toBe("true");
    expect(historyEntries[1].textContent).toContain("Showing");
    expect(container.querySelector("section")?.textContent).toContain("100");
  });
});
