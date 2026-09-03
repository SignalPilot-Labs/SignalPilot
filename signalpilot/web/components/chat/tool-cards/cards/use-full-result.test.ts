import { act, createElement, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ChatUiContext, type ChatUiContextValue } from "~/components/chat/chat-ui-context";
import {
  FULL_RESULT_MAX_ROWS,
  FULL_RESULT_PAGE_SIZE,
  pageFullResult,
  useFullResult,
  type FullResultState,
} from "./use-full-result";

vi.mock("~/lib/api/chat-results", () => ({
  getConversationToolResult: vi.fn(),
}));
import { getConversationToolResult } from "~/lib/api/chat-results";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const columns = [{ name: "id", logical_type: "integer" }];

function page(offset: number, limit: number, total: number) {
  const end = Math.min(total, offset + limit);
  return {
    result_id: "res-31",
    execution_id: null,
    columns,
    rows: Array.from({ length: Math.max(0, end - offset) }, (_, i) => [offset + i]),
    offset,
    limit,
    saved_row_count: total,
    query_row_count: total,
    completeness: "complete",
    truncation_reason: null,
    connection_name: null,
  };
}

function Probe({
  onState,
  conversationId,
  resultId,
  total,
}: {
  onState: (state: FullResultState) => void;
  conversationId: string | null;
  resultId: string | null;
  total: number | null;
}) {
  onState(useFullResult(conversationId, resultId, total));
  return null;
}

describe("pageFullResult", () => {
  it("pages in 1,000s up to the row count", async () => {
    const fetcher = vi.fn(async (_id: string, opts: { offset: number; limit: number }) =>
      page(opts.offset, opts.limit, 2_500),
    );
    const out = await pageFullResult(fetcher, "res-31", 2_500);
    expect(out.rows).toHaveLength(2_500);
    expect(out.columns).toEqual([{ name: "id", type: "integer" }]);
    expect(fetcher.mock.calls.map(([, opts]) => opts)).toEqual([
      { offset: 0, limit: FULL_RESULT_PAGE_SIZE },
      { offset: 1_000, limit: FULL_RESULT_PAGE_SIZE },
      { offset: 2_000, limit: 500 },
    ]);
  });
  it("caps at 10,000 rows and stops on a short page", async () => {
    const fetcher = vi.fn(async (_id: string, opts: { offset: number; limit: number }) =>
      page(opts.offset, opts.limit, 50_000),
    );
    const capped = await pageFullResult(fetcher, "res-31", 50_000);
    expect(capped.rows).toHaveLength(FULL_RESULT_MAX_ROWS);
    expect(fetcher).toHaveBeenCalledTimes(10);
    const short = vi.fn(async (_id: string, opts: { offset: number; limit: number }) =>
      page(opts.offset, opts.limit, 120),
    );
    const out = await pageFullResult(short, "res-31", null);
    expect(out.rows).toHaveLength(120);
    expect(short).toHaveBeenCalledTimes(1);
  });
});

describe("useFullResult", () => {
  let container: HTMLDivElement;
  let root: Root;
  let latest: FullResultState;
  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    vi.mocked(getConversationToolResult).mockReset();
  });
  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (
    ui: Partial<ChatUiContextValue> | null,
    props: { conversationId: string | null; resultId: string | null; total: number | null },
  ) => {
    const probe = createElement(Probe, {
      ...props,
      onState: (state: FullResultState) => {
        latest = state;
      },
    });
    const tree: ReactNode = ui
      ? createElement(ChatUiContext.Provider, { value: ui as ChatUiContextValue }, probe)
      : probe;
    await act(async () => root.render(tree));
  };

  it("prefers the context override and reports ready", async () => {
    const getToolResultRows = vi.fn(
      async (_id: string, opts?: { offset?: number; limit?: number }) =>
        page(opts?.offset ?? 0, opts?.limit ?? 500, 1_204),
    );
    await render({ getToolResultRows }, { conversationId: "c1", resultId: "res-31", total: 1_204 });
    expect(latest.status).toBe("idle");
    await act(async () => latest.load());
    expect(latest.status).toBe("ready");
    expect(latest.rows).toHaveLength(1_204);
    expect(latest.columns[0]).toEqual({ name: "id", type: "integer" });
    expect(getToolResultRows).toHaveBeenCalledTimes(2);
    expect(getConversationToolResult).not.toHaveBeenCalled();
    // Ready results are not refetched.
    await act(async () => latest.load());
    expect(getToolResultRows).toHaveBeenCalledTimes(2);
  });

  it("falls back to the API fetcher, paging by conversation", async () => {
    vi.mocked(getConversationToolResult).mockImplementation(
      async (_conversationId, _resultId, opts = {}) =>
        page(opts.offset ?? 0, opts.limit ?? 500, 1_500),
    );
    await render({}, { conversationId: "conv-9", resultId: "res-31", total: 1_500 });
    await act(async () => latest.load());
    expect(latest.status).toBe("ready");
    expect(latest.rows).toHaveLength(1_500);
    expect(vi.mocked(getConversationToolResult).mock.calls[0][0]).toBe("conv-9");
    expect(vi.mocked(getConversationToolResult).mock.calls[0][1]).toBe("res-31");
    expect(vi.mocked(getConversationToolResult).mock.calls[1][2]).toEqual({
      offset: 1_000,
      limit: 500,
    });
  });

  it("stays idle without a conversation or result id", async () => {
    await render({}, { conversationId: null, resultId: "res-31", total: 10 });
    await act(async () => latest.load());
    expect(latest.status).toBe("idle");
    expect(getConversationToolResult).not.toHaveBeenCalled();
    await render({}, { conversationId: "c1", resultId: null, total: 10 });
    await act(async () => latest.load());
    expect(latest.status).toBe("idle");
  });

  it("surfaces a fetch failure as the error state", async () => {
    vi.mocked(getConversationToolResult).mockRejectedValue(new Error("403 forbidden"));
    await render({}, { conversationId: "c1", resultId: "res-31", total: 10 });
    await act(async () => latest.load());
    expect(latest.status).toBe("error");
    expect(latest.error).toBe("403 forbidden");
    expect(latest.rows).toEqual([]);
  });
});
