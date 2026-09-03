import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ChatUiContext,
  type ChatUiContextValue,
} from "~/components/chat/chat-ui-context";
import {
  MessageRunContext,
  type MessageRunContextValue,
} from "~/components/chat/message-run-context";
import type { ConversationFileInfo } from "~/lib/api";
import { ChatMarkdown } from "./chat-markdown";
import { MarkdownImage } from "./image";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

function file(
  path: string,
  overrides: Partial<ConversationFileInfo> = {},
): ConversationFileInfo {
  return {
    id: `id-${path}`,
    path,
    filename: path.split("/").pop() ?? path,
    kind: "image",
    mime_type: "image/png",
    byte_size: 4_096,
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
    openArtifact: vi.fn(),
    getFileObjectUrl: vi.fn(async (id: string) => `blob:${id}`),
    onStop: async () => undefined,
    onRetry: async () => undefined,
    onOpenDashboardPreview: () => undefined,
    ...overrides,
  };
}

describe("MarkdownImage", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    // jsdom has no object URLs. Patch the methods in place: replacing the
    // global would drop the URL constructor the markdown sanitizer needs.
    Object.assign(URL, {
      createObjectURL: vi.fn(() => "blob:x"),
      revokeObjectURL: vi.fn(),
    });
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (
    node: React.ReactNode,
    value: ChatUiContextValue | null,
    run: MessageRunContextValue | null = null,
  ) => {
    const inner = run ? (
      <MessageRunContext.Provider value={run}>{node}</MessageRunContext.Provider>
    ) : (
      node
    );
    await act(async () => {
      root.render(
        value ? (
          <ChatUiContext.Provider value={value}>{inner}</ChatUiContext.Provider>
        ) : (
          inner
        ),
      );
    });
  };
  const missing = () =>
    container.querySelector('[data-testid="chat-md-image-missing"]');
  const pending = () =>
    container.querySelector('[data-testid="chat-md-figure-pending"]');

  it("renders an external image as a plain img", async () => {
    await render(
      <MarkdownImage src="https://example.com/x.png" alt="ext" />,
      ui({}),
    );
    const img = container.querySelector("img");
    expect(img?.getAttribute("src")).toBe("https://example.com/x.png");
    expect(container.querySelector("figure")).toBeNull();
  });

  it("renders a relative image as a plain img when no context is present", async () => {
    await render(<MarkdownImage src="artifacts/x.png" alt="chart" />, null);
    const img = container.querySelector("img");
    expect(img?.getAttribute("src")).toBe("artifacts/x.png");
    expect(container.querySelector('[data-testid="chat-md-figure-pending"]')).toBeNull();
  });

  it("renders the not-available band for a sentinel-origin image without a context", async () => {
    // ChatMarkdown's sanitizer rebases relative targets onto the sentinel
    // origin; with no manifest to resolve against, a band beats a broken img.
    await render(
      <MarkdownImage
        src="https://conversation-files.invalid/artifacts/x.png"
        alt="chart"
      />,
      null,
    );
    expect(missing()?.textContent).toContain("Image not available");
    expect(missing()?.textContent).toContain("x.png");
    expect(container.querySelector("img")).toBeNull();
  });

  it("shows the band, never a broken image, through ChatMarkdown without a context", async () => {
    await render(<ChatMarkdown markdown="![Chart](artifacts/x.png)" />, null);
    expect(container.querySelector("img")).toBeNull();
    expect(missing()?.textContent).toContain("x.png");
  });

  it("renders a pending placeholder while this message's run streams", async () => {
    await render(
      <MarkdownImage src="artifacts/x.png" alt="chart" />,
      ui({}),
      { runId: "run-1", running: true },
    );
    expect(pending()?.getAttribute("aria-busy")).toBe("true");
    expect(pending()?.textContent).toContain("x.png");
    expect(missing()).toBeNull();
  });

  it("renders the missing band once this message's run ended", async () => {
    await render(
      <MarkdownImage src="artifacts/x.png" alt="chart" />,
      ui({}),
      { runId: "run-1", running: false },
    );
    expect(missing()?.textContent).toContain("Image not available");
    expect(missing()?.textContent).toContain("x.png");
    expect(pending()).toBeNull();
  });

  it("stays missing for an old message while a later run is streaming", async () => {
    // The old message's own run finished. Another run streaming elsewhere
    // in the conversation must not flip it back to a shimmer.
    await render(
      <MarkdownImage src="artifacts/x.png" alt="chart" />,
      ui({}),
      { runId: "run-1", running: false },
    );
    expect(missing()).not.toBeNull();
    expect(pending()).toBeNull();
    // No message context at all (playground): never pending.
    await render(<MarkdownImage src="artifacts/x.png" alt="chart" />, ui({}));
    expect(missing()).not.toBeNull();
    expect(pending()).toBeNull();
  });

  it("renders the missing state as a block on its own line, never inline", async () => {
    await render(
      <ChatMarkdown markdown="See the chart ![Chart](artifacts/gone.png) above." />,
      ui({}),
      { runId: "run-1", running: false },
    );
    const band = missing();
    expect(band?.getAttribute("role")).toBe("status");
    expect(band?.classList.contains("chat-md-image-missing")).toBe(true);
    expect(band?.textContent).toContain("Image not available");
    expect(band?.textContent).toContain("gone.png");
    // Never the inline chip for an image reference.
    expect(
      container.querySelector('[data-testid="chat-md-file-chip-missing"]'),
    ).toBeNull();
  });

  it("renders a captioned figure with actions for a resolved image", async () => {
    const openArtifact = vi.fn();
    const row = file("artifacts/x.png");
    await render(
      <MarkdownImage src="artifacts/x.png" alt="Revenue by month" />,
      ui({ files: [row], openArtifact }),
    );
    const figure = container.querySelector('[data-testid="chat-md-figure"]');
    expect(figure).not.toBeNull();
    expect(figure?.querySelector("img")?.getAttribute("src")).toBe(
      "blob:id-artifacts/x.png",
    );
    expect(figure?.querySelector("figcaption")?.textContent).toBe(
      "Revenue by month",
    );
    const open = container.querySelector<HTMLButtonElement>(
      '[data-testid="chat-md-figure-open"]',
    );
    await act(async () => open?.click());
    expect(openArtifact).toHaveBeenCalledWith("id-artifacts/x.png");
    expect(container.querySelector('[data-testid="chat-md-figure-download"]')).not.toBeNull();
  });

  it("opens the lightbox on click", async () => {
    await render(
      <MarkdownImage src="artifacts/x.png" alt="Revenue" />,
      ui({ files: [file("artifacts/x.png")] }),
    );
    const button = container.querySelector<HTMLButtonElement>(
      ".chat-md-figure-button",
    );
    await act(async () => button?.click());
    const lightbox = document.querySelector('[data-testid="artifact-lightbox"]');
    expect(lightbox?.getAttribute("aria-label")).toBe("x.png");
    expect(lightbox?.querySelector("img")?.getAttribute("src")).toBe(
      "blob:id-artifacts/x.png",
    );
  });

  it("swaps the image when the content hash changes", async () => {
    const getFileObjectUrl = vi.fn(async (id: string) => `blob:${id}:${getFileObjectUrl.mock.calls.length}`);
    const base = ui({ files: [file("artifacts/x.png")], getFileObjectUrl });
    await render(<MarkdownImage src="artifacts/x.png" alt="a" />, base);
    const first = container.querySelector("img")?.getAttribute("src");
    await render(
      <MarkdownImage src="artifacts/x.png" alt="a" />,
      { ...base, files: [file("artifacts/x.png", { content_hash: "h2" })] },
    );
    expect(getFileObjectUrl).toHaveBeenCalledTimes(2);
    expect(container.querySelector("img")?.getAttribute("src")).not.toBe(first);
  });

  it("renders a file chip when the reference resolves to a non-image", async () => {
    await render(
      <MarkdownImage src="artifacts/rows.csv" alt="rows" />,
      ui({ files: [file("artifacts/rows.csv", { kind: "data", mime_type: "text/csv" })] }),
    );
    const chip = container.querySelector('[data-testid="chat-md-file-chip"]');
    expect(chip?.getAttribute("data-kind")).toBe("data");
    expect(chip?.textContent).toContain("Preview");
  });

  it("is wired into ChatMarkdown as the img override", async () => {
    await render(
      <ChatMarkdown markdown="Look:\n\n![Revenue](artifacts/x.png)\n" />,
      ui({ files: [file("artifacts/x.png")] }),
    );
    expect(container.querySelector('[data-testid="chat-md-figure"]')).not.toBeNull();
  });
});
