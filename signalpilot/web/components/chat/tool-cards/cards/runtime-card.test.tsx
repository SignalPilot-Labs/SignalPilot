import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ChatUiContext, type ChatUiContextValue } from "~/components/chat/chat-ui-context";
import type { ConversationFileInfo } from "~/lib/api";
import type { ArtifactResult, RunStep } from "~/lib/chat-run-steps";
import { ToolCard } from "../tool-card";
import { summarizeArtifact } from "./runtime-card";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const NOTEBOOK_PATH = "/tmp/signalpilot-chat-runs/run-1/analysis.py";

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
  summary: "Started the analysis notebook",
  resultText: null,
  resultChars: null,
  truncated: false,
  errorMessage: null,
  artifactKind: "notebook",
  published: false,
  filename: null,
  artifactIndex: null,
  status: null,
  nextRequiredAction: null,
  sessionId: "gw-1",
  notebookPath: NOTEBOOK_PATH,
  notebook: "analysis",
  dashboardSessionId: null,
  ...overrides,
});

const file = {
  id: "file-7",
  path: "analysis.py",
  filename: "analysis",
  kind: "notebook",
  mime_type: "text/x-python",
  byte_size: 2048,
  content_hash: "abc",
  origin_run_id: "run-1",
  origin: "runtime",
  status: "active",
  created_at: "2026-09-01T12:00:00.000Z",
  updated_at: "2026-09-01T12:00:00.000Z",
} as unknown as ConversationFileInfo;

function step(overrides: Partial<RunStep> = {}): RunStep {
  return {
    key: "n1",
    sequence: 27,
    category: "artifact",
    status: "succeeded",
    title: "Started the analysis notebook",
    tool: "start_analysis_notebook",
    toolOrigin: "chat",
    input: { notebook: "analysis" },
    sql: null,
    code: null,
    file: null,
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
  it("titles notebook and dashboard steps by kind and uses the name as the stat", () => {
    expect(summarizeArtifact(step({ result: artifact() }))).toEqual({
      title: "Notebook started",
      stat: "analysis",
      ok: true,
    });
    // Without a structured result the tool name still picks the kind.
    expect(summarizeArtifact(step())).toMatchObject({
      title: "Notebook started",
      stat: "analysis",
    });
    expect(
      summarizeArtifact(step({ tool: "create_dashboard_preview", input: {} })).title,
    ).toBe("Dashboard preview");
  });
  it("keeps the step title for an unknown artifact kind", () => {
    expect(
      summarizeArtifact(step({ tool: "some_future_tool", title: "Did a thing", input: {} })),
    ).toMatchObject({ title: "Did a thing", stat: null, ok: true });
    expect(
      summarizeArtifact(step({ tool: "some_future_tool", title: "", input: {} })).title,
    ).toBe("Artifact");
  });
  it("is not ok when failed", () => {
    expect(summarizeArtifact(step({ status: "failed" })).ok).toBe(false);
  });
});

describe("runtime card", () => {
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
      conversationId: "conv-1",
      files,
      runningRunId: null,
      openArtifact,
      onStop: async () => undefined,
      onRetry: async () => undefined,
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

  it("shows the notebook name with the orbiting icon while running", async () => {
    await render(step({ status: "running", endedAt: null, durationMs: null }));
    const body = q(container, '[data-testid="chat-runtime-card"]');
    expect(body?.textContent).toContain("analysis");
    expect(q(body!, ".chat-boot-orbit")).not.toBeNull();
    expect(q(body!, '[data-testid="chat-runtime-kind"]')?.textContent).toBe("notebook");
  });

  it("offers Open only when the manifest carries the file", async () => {
    await render(
      step({
        result: artifact({ nextRequiredAction: "Run the cells to populate the notebook." }),
      }),
    );
    const chip = q(container, '[data-testid="chat-tool-chip"]') as HTMLButtonElement;
    expect(chip.textContent).toContain("Notebook started");
    await act(async () => chip.click());
    expect(q(container, '[data-testid="chat-runtime-next"]')?.textContent).toContain(
      "populate the notebook",
    );
    expect(q(container, '[data-testid="chat-runtime-open"]')).toBeNull();

    await render(step({ result: artifact() }), [file]);
    const open = q(container, '[data-testid="chat-runtime-open"]') as HTMLButtonElement;
    expect(open).not.toBeNull();
    await act(async () => open.click());
    expect(openArtifact).toHaveBeenCalledWith("file-7");
  });

  it("delegates dashboard previews to the existing details body", async () => {
    await render(
      step({
        tool: "create_dashboard_preview",
        title: "Creating dashboard preview",
        input: { request: "Regional revenue by quarter", timezone: "America/New_York" },
        result: artifact({
          artifactKind: "dashboard",
          notebook: null,
          notebookPath: null,
          dashboardSessionId: "dash-1",
        }),
      }),
    );
    const chip = q(container, '[data-testid="chat-tool-chip"]') as HTMLButtonElement;
    expect(chip.textContent).toContain("Dashboard preview");
    await act(async () => chip.click());
    const body = q(container, '[data-testid="chat-runtime-card"]');
    expect(body?.textContent).toContain("Regional revenue by quarter");
    expect(body?.textContent).toContain("America/New_York");
    expect(q(body!, '[data-testid="chat-runtime-kind"]')).toBeNull();
  });

  it("degrades a legacy completion to the name from the input", async () => {
    await render(step({ result: LEGACY }));
    const chip = q(container, '[data-testid="chat-tool-chip"]') as HTMLButtonElement;
    expect(chip.textContent).toContain("Notebook started");
    await act(async () => chip.click());
    expect(q(container, '[data-testid="chat-runtime-card"]')?.textContent).toContain("analysis");
    expect(q(container, '[data-testid="chat-runtime-next"]')).toBeNull();
  });
});
