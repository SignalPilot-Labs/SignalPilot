import { act, createElement, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ChatUiContext,
  type ChatUiContextValue,
} from "~/components/chat/chat-ui-context";
import {
  fileObjectUrlCacheSize,
  fileObjectUrlKey,
  useFileObjectUrl,
  type FileObjectUrlState,
} from "./use-file-object-url";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

type FileRef = { id: string; content_hash: string };

function Probe({
  file,
  conversationId,
  onState,
}: {
  file: FileRef | null;
  conversationId: string | null;
  onState: (state: FileObjectUrlState) => void;
}) {
  onState(useFileObjectUrl(file, conversationId));
  return null;
}

describe("useFileObjectUrl", () => {
  let container: HTMLDivElement;
  let root: Root;
  let revoke: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    revoke = vi.fn();
    // jsdom has no object URLs; patch the methods in place.
    Object.assign(URL, {
      createObjectURL: vi.fn(() => "blob:unused"),
      revokeObjectURL: revoke,
    });
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (
    tree: ReactNode,
  ) => {
    await act(async () => root.render(tree));
  };

  const withUi = (
    getFileObjectUrl: (fileId: string) => Promise<string>,
    children: ReactNode,
  ) =>
    createElement(
      ChatUiContext.Provider,
      { value: { getFileObjectUrl } as ChatUiContextValue },
      children,
    );

  it("fetches once per version and revokes when the last consumer unmounts", async () => {
    const fetcher = vi.fn(async (id: string) => `blob:${id}`);
    const file = { id: "f1", content_hash: "h1" };
    let a: FileObjectUrlState | null = null;
    let b: FileObjectUrlState | null = null;
    await render(
      withUi(fetcher, [
        createElement(Probe, { key: "a", file, conversationId: "c", onState: (s) => (a = s) }),
        createElement(Probe, { key: "b", file, conversationId: "c", onState: (s) => (b = s) }),
      ]),
    );
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(a!.url).toBe("blob:f1");
    expect(b!.url).toBe("blob:f1");
    expect(a!.fresh).toBe(true);
    expect(fileObjectUrlCacheSize()).toBe(1);
    // One consumer leaves: the URL stays alive for the other.
    await render(
      withUi(fetcher, [
        createElement(Probe, { key: "a", file, conversationId: "c", onState: (s) => (a = s) }),
      ]),
    );
    expect(revoke).not.toHaveBeenCalled();
    await render(withUi(fetcher, []));
    expect(revoke).toHaveBeenCalledWith("blob:f1");
    expect(fileObjectUrlCacheSize()).toBe(0);
  });

  it("refetches when the content hash changes and keeps the old url meanwhile", async () => {
    let resolveNext: ((url: string) => void) | null = null;
    const fetcher = vi.fn((id: string) => {
      if (id === "f1" && fetcher.mock.calls.length > 1) {
        return new Promise<string>((resolve) => {
          resolveNext = resolve;
        });
      }
      return Promise.resolve("blob:v1");
    });
    let state: FileObjectUrlState | null = null;
    await render(
      withUi(fetcher, createElement(Probe, {
        file: { id: "f1", content_hash: "h1" },
        conversationId: "c",
        onState: (s) => (state = s),
      })),
    );
    expect(state!.url).toBe("blob:v1");
    await render(
      withUi(fetcher, createElement(Probe, {
        file: { id: "f1", content_hash: "h2" },
        conversationId: "c",
        onState: (s) => (state = s),
      })),
    );
    expect(fetcher).toHaveBeenCalledTimes(2);
    // The previous version's URL is revoked (no consumer left) but still
    // reported as the stale image until the new one resolves.
    expect(state!.url).toBe("blob:v1");
    expect(state!.fresh).toBe(false);
    await act(async () => {
      resolveNext?.("blob:v2");
    });
    expect(state!.url).toBe("blob:v2");
    expect(state!.fresh).toBe(true);
  });

  it("survives a release and re-acquire while the first fetch is in flight", async () => {
    // React StrictMode runs mount, unmount, mount. The orphaned first
    // entry must revoke only its own URL and leave the second entry alone.
    const resolvers: Array<(url: string) => void> = [];
    const fetcher = vi.fn(
      () =>
        new Promise<string>((resolve) => {
          resolvers.push(resolve);
        }),
    );
    let state: FileObjectUrlState | null = null;
    const file = { id: "f4", content_hash: "h1" };
    const probe = () =>
      createElement(Probe, { file, conversationId: "c", onState: (s) => (state = s) });
    await render(withUi(fetcher, probe()));
    await render(withUi(fetcher, []));
    await render(withUi(fetcher, probe()));
    expect(fetcher).toHaveBeenCalledTimes(2);
    await act(async () => resolvers[0]("blob:first"));
    expect(revoke).toHaveBeenCalledWith("blob:first");
    expect(fileObjectUrlCacheSize()).toBe(1);
    await act(async () => resolvers[1]("blob:second"));
    expect(revoke).not.toHaveBeenCalledWith("blob:second");
    expect(state!.url).toBe("blob:second");
    expect(state!.fresh).toBe(true);
  });

  it("reports an error and does not cache the failure", async () => {
    const fetcher = vi
      .fn<(id: string) => Promise<string>>()
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce("blob:ok");
    let state: FileObjectUrlState | null = null;
    const file = { id: "f2", content_hash: "h1" };
    await render(
      withUi(fetcher, createElement(Probe, { file, conversationId: "c", onState: (s) => (state = s) })),
    );
    expect(state!.error?.message).toBe("boom");
    expect(state!.url).toBeNull();
    expect(fileObjectUrlCacheSize()).toBe(0);
    await render(withUi(fetcher, []));
    await render(
      withUi(fetcher, createElement(Probe, { file, conversationId: "c", onState: (s) => (state = s) })),
    );
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(state!.url).toBe("blob:ok");
  });

  it("does nothing without a file, or without a conversation and override", async () => {
    let state: FileObjectUrlState | null = null;
    await render(
      createElement(Probe, { file: null, conversationId: "c", onState: (s) => (state = s) }),
    );
    expect(state).toEqual({ url: null, fresh: false, error: null });
    await render(
      createElement(Probe, {
        file: { id: "f3", content_hash: "h" },
        conversationId: null,
        onState: (s) => (state = s),
      }),
    );
    expect(state!.url).toBeNull();
    expect(fileObjectUrlCacheSize()).toBe(0);
  });

  it("keys the cache by file id and content hash", () => {
    expect(fileObjectUrlKey("f", "h")).toBe("f:h");
  });
});
