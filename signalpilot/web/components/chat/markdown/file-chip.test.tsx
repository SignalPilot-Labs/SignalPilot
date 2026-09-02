import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ChatUiContext,
  type ChatUiContextValue,
} from "~/components/chat/chat-ui-context";
import type { ConversationFileInfo } from "~/lib/api";

const downloadConversationFile = vi.fn(async () => undefined);
vi.mock("~/lib/api", () => ({
  downloadConversationFile: (...args: unknown[]) =>
    downloadConversationFile(...(args as [])),
  getConversationFileObjectUrl: vi.fn(),
}));

import { MarkdownLink } from "./link";
import { chipActionLabel, FileChip, MissingFileChip, PendingFileChip } from "./file-chip";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

function file(
  path: string,
  kind: ConversationFileInfo["kind"],
  overrides: Partial<ConversationFileInfo> = {},
): ConversationFileInfo {
  return {
    id: `id-${path}`,
    path,
    filename: path.split("/").pop() ?? path,
    kind,
    mime_type: null,
    byte_size: 2_048,
    content_hash: "h1",
    origin_run_id: "run-1",
    origin: "runtime",
    status: "active",
    created_at: "2026-01-15T17:30:00.000Z",
    updated_at: "2026-01-15T17:30:00.000Z",
    ...overrides,
  };
}

function ui(overrides: Partial<ChatUiContextValue>): ChatUiContextValue {
  return {
    events: [],
    conversationId: "conv-1",
    files: [],
    runningRunId: null,
    openArtifact: vi.fn(),
    onStop: async () => undefined,
    onRetry: async () => undefined,
    onOpenDashboardPreview: () => undefined,
    ...overrides,
  };
}

describe("FileChip", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    downloadConversationFile.mockClear();
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (node: React.ReactNode, value: ChatUiContextValue | null) => {
    await act(async () => {
      root.render(
        value ? (
          <ChatUiContext.Provider value={value}>{node}</ChatUiContext.Provider>
        ) : (
          node
        ),
      );
    });
  };

  it("picks the primary verb by kind", () => {
    expect(chipActionLabel("data")).toBe("Preview");
    expect(chipActionLabel("html")).toBe("Open");
    expect(chipActionLabel("markdown")).toBe("Open");
    expect(chipActionLabel("image")).toBe("Download");
    expect(chipActionLabel("code")).toBe("Download");
    expect(chipActionLabel("other")).toBe("Download");
  });

  it("previews data files in the panel", async () => {
    const value = ui({});
    await render(<FileChip file={file("artifacts/rows.csv", "data")} ui={value} />, value);
    const chip = container.querySelector<HTMLButtonElement>('[data-testid="chat-md-file-chip"]');
    expect(chip?.textContent).toContain("rows.csv");
    expect(chip?.textContent).toContain("2.0 KB");
    expect(chip?.textContent).toContain("Preview");
    await act(async () => chip?.click());
    expect(value.openArtifact).toHaveBeenCalledWith("id-artifacts/rows.csv");
    expect(downloadConversationFile).not.toHaveBeenCalled();
  });

  it("opens html and markdown in the panel", async () => {
    const value = ui({});
    await render(<FileChip file={file("artifacts/report.html", "html")} ui={value} />, value);
    expect(container.textContent).toContain("Open");
    await act(async () =>
      container.querySelector<HTMLButtonElement>("button")?.click(),
    );
    expect(value.openArtifact).toHaveBeenCalledWith("id-artifacts/report.html");
  });

  it("downloads other kinds through the authenticated helper", async () => {
    const value = ui({});
    await render(<FileChip file={file("artifacts/x.png", "image")} ui={value} />, value);
    await act(async () =>
      container.querySelector<HTMLButtonElement>("button")?.click(),
    );
    expect(downloadConversationFile).toHaveBeenCalledWith(
      "conv-1",
      "id-artifacts/x.png",
      "x.png",
    );
    expect(value.openArtifact).not.toHaveBeenCalled();
  });

  it("middle-truncates long names", async () => {
    const value = ui({});
    const long = "a_very_long_file_name_that_keeps_going_and_going_forever.csv";
    await render(<FileChip file={file(`artifacts/${long}`, "data")} ui={value} />, value);
    const name = container.querySelector(".chat-md-chip-name")?.textContent ?? "";
    expect(name).toContain("…");
    expect(name.endsWith(".csv")).toBe(true);
  });

  it("renders pending and missing variants", async () => {
    await render(
      <>
        <PendingFileChip name="rows.csv" />
        <MissingFileChip name="gone.csv" />
      </>,
      null,
    );
    const pending = container.querySelector('[data-testid="chat-md-file-chip-pending"]');
    expect(pending?.getAttribute("aria-busy")).toBe("true");
    expect(pending?.textContent).toContain("rows.csv");
    const missing = container.querySelector('[data-testid="chat-md-file-chip-missing"]');
    expect(missing?.textContent).toContain("File not available");
    expect(missing?.textContent).toContain("gone.csv");
  });
});

describe("MarkdownLink", () => {
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

  const render = async (node: React.ReactNode, value: ChatUiContextValue | null) => {
    await act(async () => {
      root.render(
        value ? (
          <ChatUiContext.Provider value={value}>{node}</ChatUiContext.Provider>
        ) : (
          node
        ),
      );
    });
  };

  it("renders a chip for a resolved file reference", async () => {
    await render(
      <MarkdownLink href="artifacts/rows.csv">Download rows</MarkdownLink>,
      ui({ files: [file("artifacts/rows.csv", "data")] }),
    );
    expect(container.querySelector('[data-testid="chat-md-file-chip"]')).not.toBeNull();
    expect(container.querySelector("a")).toBeNull();
  });

  it("renders a chip for an absolute sandbox path", async () => {
    await render(
      <MarkdownLink href="/tmp/signalpilot-chat-runs/run-1/artifacts/rows.csv">x</MarkdownLink>,
      ui({ files: [file("artifacts/rows.csv", "data")] }),
    );
    expect(container.querySelector('[data-testid="chat-md-file-chip"]')).not.toBeNull();
  });

  it("renders pending then missing for an unresolved relative reference", async () => {
    await render(
      <MarkdownLink href="artifacts/rows.csv">x</MarkdownLink>,
      ui({ runningRunId: "run-1" }),
    );
    expect(container.querySelector('[data-testid="chat-md-file-chip-pending"]')).not.toBeNull();
    await render(<MarkdownLink href="artifacts/rows.csv">x</MarkdownLink>, ui({}));
    expect(container.querySelector('[data-testid="chat-md-file-chip-missing"]')).not.toBeNull();
  });

  it("keeps root-relative app routes as in-app links", async () => {
    await render(
      <MarkdownLink href="/lineage/fct_orders">fct_orders</MarkdownLink>,
      ui({}),
    );
    const anchor = container.querySelector("a");
    expect(anchor?.getAttribute("href")).toBe("/lineage/fct_orders");
    expect(anchor?.getAttribute("target")).toBeNull();
  });

  it("keeps external links as new-tab anchors, with or without a context", async () => {
    await render(<MarkdownLink href="https://example.com">e</MarkdownLink>, ui({}));
    expect(container.querySelector("a")?.getAttribute("target")).toBe("_blank");
    await render(<MarkdownLink href="artifacts/rows.csv">e</MarkdownLink>, null);
    expect(container.querySelector("a")?.getAttribute("href")).toBe("artifacts/rows.csv");
  });
});
