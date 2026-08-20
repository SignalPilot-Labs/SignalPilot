import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  getChatReportMentions: vi.fn(),
}));

vi.mock("~/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("~/lib/api")>();
  return {
    ...original,
    getChatReportMentions: mocks.getChatReportMentions,
  };
});

import { StandaloneChatComposer } from "~/components/chat/standalone-chat-composer";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

describe("Standalone Data Chat report mentions", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    mocks.getChatReportMentions.mockResolvedValue({
      items: [
        {
          report_id: "report-1",
          title: "Quarterly revenue",
          kind: "table",
          project_id: "project-1",
          current_version_id: "version-2",
        },
      ],
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

  it("attaches only an explicitly selected owner report as structured state", async () => {
    const selected = vi.fn();
    await act(async () => {
      root.render(
        <StandaloneChatComposer
          value="Compare this with @rev"
          onValueChange={vi.fn()}
          onSubmit={vi.fn()}
          submitDisabled={false}
          placeholder="Ask"
          projectId="project-1"
          onSelectedReportChange={selected}
        />,
      );
    });
    await act(async () => {
      await Promise.resolve();
    });

    expect(mocks.getChatReportMentions).toHaveBeenCalledWith(
      "project-1",
      "rev",
    );
    const option =
      container.querySelector<HTMLButtonElement>('[role="option"]');
    expect(option?.textContent).toContain("Quarterly revenue");
    await act(async () => option?.click());
    expect(selected).toHaveBeenCalledWith({
      report_id: "report-1",
      title: "Quarterly revenue",
      kind: "table",
      project_id: "project-1",
      current_version_id: "version-2",
    });
  });

  it("does not infer a report from plain text", async () => {
    await act(async () => {
      root.render(
        <StandaloneChatComposer
          value="Compare this with the quarterly revenue report"
          onValueChange={vi.fn()}
          onSubmit={vi.fn()}
          submitDisabled={false}
          placeholder="Ask"
          projectId="project-1"
          onSelectedReportChange={vi.fn()}
        />,
      );
    });

    expect(mocks.getChatReportMentions).not.toHaveBeenCalled();
    expect(container.querySelector('[role="listbox"]')).toBeNull();
  });
});
