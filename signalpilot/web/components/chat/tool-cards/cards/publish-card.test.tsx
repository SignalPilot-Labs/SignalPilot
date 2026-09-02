import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ChatUiContext, type ChatUiContextValue } from "~/components/chat/chat-ui-context";
import type { ConversationFileInfo } from "~/lib/api";
import type { ArtifactResult, RunStep } from "~/lib/chat-run-steps";
import { ToolCard } from "../tool-card";
import { summarizeArtifact } from "./publish-card";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const FILENAME = "q3_revenue_by_region.csv";

const LEGACY = {
  kind: "legacy",
  summary: null,
  resultText: null,
  resultChars: null,
  truncated: false,
  errorMessage: null,
} as const;

const artifact = (overrides: Partial<ArtifactResult> = {}): ArtifactResult => ({
  kind: "artifact",
  summary: `Published ${FILENAME}`,
  resultText: null,
  resultChars: null,
  truncated: false,
  errorMessage: null,
  artifactKind: "table",
  published: true,
  filename: FILENAME,
  artifactIndex: 1,
  status: "published",
  nextRequiredAction: null,
  sessionId: null,
  notebookPath: null,
  notebook: null,
  dashboardSessionId: null,
  ...overrides,
});

const file = {
  id: "file-31",
  path: `exports/${FILENAME}`,
  filename: FILENAME,
  kind: "csv",
  mime_type: "text/csv",
  byte_size: 2048,
  content_hash: "abc",
  origin_run_id: "run-1",
  origin: "publish_table",
  status: "ready",
  created_at: "2026-09-01T12:00:00.000Z",
  updated_at: "2026-09-01T12:00:00.000Z",
} as unknown as ConversationFileInfo;

function step(overrides: Partial<RunStep> = {}): RunStep {
  return {
    key: "p1",
    sequence: 27,
    category: "artifact",
    status: "succeeded",
    title: "Published a table",
    tool: "publish_table",
    toolOrigin: "chat",
    input: { filename: FILENAME, result_id: "res-31" },
    sql: null,
    code: null,
    file: FILENAME,
    sources: [],
    detail: null,
    result: null,
    startedAt: "2026-09-01T12:00:00.000Z",
    endedAt: "2026-09-01T12:00:00.700Z",
    durationMs: 700,
    children: [],
    subagentType: null,
    report: null,
    liveText: "",
    ...overrides,
  };
}

const q = (root: ParentNode, selector: string) => root.querySelector(selector);

describe("summarizeArtifact", () => {
  it("keeps the humanized publish title and uses the filename as the stat", () => {
    expect(summarizeArtifact(step({ result: artifact() }))).toEqual({
      title: "Published a table",
      stat: FILENAME,
      ok: true,
    });
    expect(
      summarizeArtifact(
        step({
          tool: "publish_chart",
          title: "Published a chart",
          input: { filename: "growth.vl.json" },
          file: null,
        }),
      ),
    ).toMatchObject({ title: "Published a chart", stat: "growth.vl.json" });
    // Only a step without a title falls back to the kind.
    expect(summarizeArtifact(step({ title: "", result: artifact() })).title).toBe("Published table");
    expect(
      summarizeArtifact(step({ title: "", result: artifact({ published: false }) })).title,
    ).toBe("Publishing table");
    expect(
      summarizeArtifact(
        step({
          tool: "start_analysis_notebook",
          input: {},
          file: null,
          result: artifact({
            artifactKind: "notebook",
            published: false,
            filename: null,
            notebook: "analysis",
          }),
        }),
      ),
    ).toEqual({ title: "Notebook started", stat: "analysis", ok: true });
    expect(
      summarizeArtifact(step({ tool: "create_dashboard_preview", input: {}, file: null })).title,
    ).toBe("Dashboard preview");
  });
  it("is not ok when unpublished or failed", () => {
    expect(summarizeArtifact(step({ result: artifact({ published: false }) })).ok).toBe(false);
    expect(summarizeArtifact(step({ status: "failed" })).ok).toBe(false);
  });
});

describe("publish card", () => {
  let container: HTMLDivElement;
  let root: Root;
  const openArtifact = vi.fn();
  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    openArtifact.mockReset();
  });
  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });
  const render = async (s: RunStep, files: ConversationFileInfo[] = []) => {
    const ui = {
      events: [],
      artifacts: [],
      conversationId: "conv-1",
      files,
      openArtifact,
      onStop: async () => undefined,
      onRetry: async () => undefined,
      onApproveReportSuggestion: async () => ({ report_id: "r" }),
      onOpenDashboardPreview: () => undefined,
    } as ChatUiContextValue;
    await act(async () => {
      root.render(
        <ChatUiContext.Provider value={ui}>
          <ol>
            <ToolCard step={s} groupLive isLastInGroup />
          </ol>
        </ChatUiContext.Provider>,
      );
    });
  };

  it("shows the filename with the orbiting icon while running", async () => {
    await render(step({ status: "running", endedAt: null, durationMs: null }));
    const body = q(container, '[data-testid="chat-publish-card"]');
    expect(body?.textContent).toContain(FILENAME);
    expect(q(body!, ".chat-boot-orbit")).not.toBeNull();
    expect(q(body!, '[data-testid="chat-publish-kind"]')?.textContent).toBe("table");
  });

  it("offers Open only when the manifest carries the file", async () => {
    await render(
      step({
        result: artifact({ nextRequiredAction: "Share the table with the finance channel." }),
      }),
    );
    const chip = q(container, '[data-testid="chat-tool-chip"]') as HTMLButtonElement;
    expect(chip.textContent).toContain(FILENAME);
    await act(async () => chip.click());
    expect(q(container, '[data-testid="chat-publish-next"]')?.textContent).toContain(
      "finance channel",
    );
    expect(q(container, '[data-testid="chat-publish-open"]')).toBeNull();

    await render(step({ result: artifact() }), [file]);
    const open = q(container, '[data-testid="chat-publish-open"]') as HTMLButtonElement;
    expect(open).not.toBeNull();
    await act(async () => open.click());
    expect(openArtifact).toHaveBeenCalledWith("file-31");
  });

  it("delegates dashboard previews to the existing details body", async () => {
    await render(
      step({
        tool: "create_dashboard_preview",
        file: null,
        input: { request: "Regional revenue by quarter", timezone: "America/New_York" },
        result: artifact({ artifactKind: "dashboard", filename: null, dashboardSessionId: "dash-1" }),
      }),
    );
    const chip = q(container, '[data-testid="chat-tool-chip"]') as HTMLButtonElement;
    expect(chip.textContent).toContain("Dashboard preview");
    await act(async () => chip.click());
    const body = q(container, '[data-testid="chat-publish-card"]');
    expect(body?.textContent).toContain("Regional revenue by quarter");
    expect(body?.textContent).toContain("America/New_York");
    expect(q(body!, '[data-testid="chat-publish-kind"]')).toBeNull();
  });

  it("degrades a legacy completion to the filename from the input", async () => {
    await render(step({ result: LEGACY }));
    const chip = q(container, '[data-testid="chat-tool-chip"]') as HTMLButtonElement;
    expect(chip.textContent).toContain("Published a table");
    await act(async () => chip.click());
    expect(q(container, '[data-testid="chat-publish-card"]')?.textContent).toContain(FILENAME);
    expect(q(container, '[data-testid="chat-publish-next"]')).toBeNull();
  });
});
