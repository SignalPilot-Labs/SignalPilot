import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  promoteChatArtifact: vi.fn(),
  routerPush: vi.fn(),
  toast: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: mocks.routerPush,
    replace: vi.fn(),
  }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("~/components/ui/toast", () => ({
  useToast: () => ({ toast: mocks.toast }),
}));

vi.mock("~/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("~/lib/api")>();
  return {
    ...original,
    promoteChatArtifact: mocks.promoteChatArtifact,
  };
});

import { ArtifactPreview } from "~/components/chat/standalone-data-chat";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const artifact = {
  id: "artifact-1",
  assistant_message_id: "message-1",
  kind: "table" as const,
  filename: "quarterly-revenue.csv",
  mime_type: "text/csv",
  snapshot: {
    columns: [{ name: "revenue" }],
    rows: [{ revenue: 100 }],
  },
  freshness_at: "2026-08-10T12:00:00Z",
  assumptions: [],
  exclusions: [],
  caveats: [],
  created_at: "2026-08-10T12:00:00Z",
  download_formats: ["csv"],
};

describe("Data Chat artifact report action", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    mocks.promoteChatArtifact.mockResolvedValue({
      status: "created",
      report_id: "report-1",
      version_id: "version-1",
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

  it("saves a completed owner-thread artifact as a report", async () => {
    await act(async () => {
      root.render(<ArtifactPreview artifact={artifact} canSaveAsReport />);
    });

    const saveAsReport = [...container.querySelectorAll("button")].find(
      (button) => button.textContent?.trim() === "Save as report",
    );
    expect(saveAsReport).not.toBeUndefined();

    await act(async () => saveAsReport?.click());
    expect(container.querySelector('[role="dialog"]')).not.toBeNull();
    expect(container.querySelector<HTMLInputElement>("input")?.value).toBe(
      "quarterly-revenue",
    );

    const saveReport = [...container.querySelectorAll("button")].find(
      (button) => button.textContent?.trim() === "Save report",
    );
    await act(async () => saveReport?.click());

    expect(mocks.promoteChatArtifact).toHaveBeenCalledWith(
      "artifact-1",
      "quarterly-revenue",
    );
    expect(mocks.toast).toHaveBeenCalledWith("Report saved", "success");
    expect(mocks.routerPush).toHaveBeenCalledWith("/reports/report-1");
  });

  it("does not expose the save action in read-only artifact previews", async () => {
    await act(async () => {
      root.render(<ArtifactPreview artifact={artifact} />);
    });

    expect(container.textContent).not.toContain("Save as report");
  });

  it("updates the originating report for a refresh artifact", async () => {
    mocks.promoteChatArtifact.mockResolvedValue({
      status: "updated",
      report_id: "report-1",
      version_id: "version-2",
    });
    await act(async () => {
      root.render(
        <ArtifactPreview
          artifact={{
            ...artifact,
            saved_report_id: "report-1",
            saved_report_version_id: "version-1",
            saved_report_title: "Quarterly revenue",
            report_action: "update",
          }}
          canSaveAsReport
        />,
      );
    });

    const updateReport = [...container.querySelectorAll("button")].find(
      (button) => button.textContent?.trim() === "Update report",
    );
    expect(updateReport).not.toBeUndefined();
    expect(container.textContent).not.toContain("Save as report");

    await act(async () => updateReport?.click());
    expect(container.querySelector('[role="dialog"]')).not.toBeNull();
    expect(container.textContent).toContain(
      "This artifact will become a new version of “Quarterly revenue”.",
    );
    expect(container.querySelector("input")).toBeNull();

    const dialog = container.querySelector('[role="dialog"]');
    const confirmUpdate = [...(dialog?.querySelectorAll("button") ?? [])].find(
      (button) => button.textContent?.trim() === "Update report",
    );
    await act(async () => confirmUpdate?.click());

    expect(mocks.promoteChatArtifact).toHaveBeenCalledWith(
      "artifact-1",
      "Quarterly revenue",
    );
    expect(mocks.toast).toHaveBeenCalledWith("Report updated", "success");
    expect(mocks.routerPush).toHaveBeenCalledWith("/reports/report-1");
  });
});
