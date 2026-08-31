import { describe, expect, it } from "vitest";
import {
  fileKindLabel,
  filesRefreshRevision,
  formatByteSize,
  hasArtifactsContent,
  sqlTraceRefreshRevision,
} from "~/lib/chat-artifacts";
import type {
  ConversationFileInfo,
  ConversationNotebook,
  SqlTraceExecution,
  StandaloneChatEvent,
} from "~/lib/api";

function event(type: StandaloneChatEvent["type"]): StandaloneChatEvent {
  return {
    run_id: "run-1",
    sequence: 1,
    type,
    payload: {},
    created_at: "2026-08-31T00:00:00Z",
  };
}

function fileInfo(overrides: Partial<ConversationFileInfo> = {}) {
  return {
    id: "file-1",
    path: "artifacts/spec.md",
    filename: "spec.md",
    kind: "markdown",
    mime_type: "text/markdown",
    byte_size: 1234,
    content_hash: "abc",
    origin_run_id: "run-1",
    origin: "mirror",
    status: "active",
    created_at: "2026-08-31T00:00:00Z",
    updated_at: "2026-08-31T00:00:00Z",
    ...overrides,
  } as ConversationFileInfo;
}

function execution(overrides: Partial<SqlTraceExecution> = {}) {
  return {
    execution_id: "exec-1",
    run_id: "run-1",
    connection_name: "warehouse",
    sql: "select 1",
    sql_hash: "hash",
    status: "completed",
    query_path: "queries/q1.sql",
    estimated_cost_usd: 0.01,
    actual_cost_usd: 0.0123,
    actual_scan_bytes: 2048,
    execution_ms: 812,
    row_count: 42,
    completeness: "complete",
    public_error_code: null,
    created_at: "2026-08-31T00:00:00Z",
    started_at: "2026-08-31T00:00:01Z",
    terminal_at: "2026-08-31T00:00:02Z",
    ...overrides,
  } as SqlTraceExecution;
}

const liveNotebook: ConversationNotebook = {
  name: "analysis",
  status: "live",
  gateway_session_id: "gw-1",
  kernel_session_id: "k-1",
  notebook_path: "analysis.ipynb",
  document: null,
};

const emptyNotebook: ConversationNotebook = {
  name: "analysis",
  status: "none",
  gateway_session_id: null,
  kernel_session_id: null,
  notebook_path: null,
  document: null,
};

describe("filesRefreshRevision", () => {
  it("counts only file events", () => {
    expect(filesRefreshRevision([])).toBe(0);
    expect(
      filesRefreshRevision([
        event("files_changed"),
        event("text_delta"),
        event("files_archived"),
        event("sql"),
        event("files_changed"),
      ]),
    ).toBe(3);
  });
});

describe("sqlTraceRefreshRevision", () => {
  it("counts only trace events", () => {
    expect(sqlTraceRefreshRevision([])).toBe(0);
    expect(
      sqlTraceRefreshRevision([
        event("sql"),
        event("query_completed"),
        event("query_cancelled"),
        event("query_started"),
        event("files_changed"),
      ]),
    ).toBe(3);
  });

  it("grows as events append", () => {
    const events = [event("sql")];
    const before = sqlTraceRefreshRevision(events);
    events.push(event("query_completed"));
    expect(sqlTraceRefreshRevision(events)).toBe(before + 1);
  });
});

describe("hasArtifactsContent", () => {
  it("is false with no notebook, files, or executions", () => {
    expect(hasArtifactsContent(null, [], [])).toBe(false);
    expect(hasArtifactsContent(emptyNotebook, [], [])).toBe(false);
  });

  it("is true when the notebook has content", () => {
    expect(hasArtifactsContent(liveNotebook, [], [])).toBe(true);
  });

  it("is true when files exist", () => {
    expect(hasArtifactsContent(null, [fileInfo()], [])).toBe(true);
  });

  it("is true when executions exist", () => {
    expect(hasArtifactsContent(null, [], [execution()])).toBe(true);
  });

  it("accepts a notebook list and checks every entry", () => {
    expect(hasArtifactsContent([], [], [])).toBe(false);
    expect(hasArtifactsContent([emptyNotebook], [], [])).toBe(false);
    expect(hasArtifactsContent([emptyNotebook, liveNotebook], [], [])).toBe(
      true,
    );
  });
});

describe("formatByteSize", () => {
  it("formats bytes below one KB as B", () => {
    expect(formatByteSize(0)).toBe("0 B");
    expect(formatByteSize(512)).toBe("512 B");
    expect(formatByteSize(1023)).toBe("1023 B");
  });

  it("formats KB and MB with one decimal", () => {
    expect(formatByteSize(1229)).toBe("1.2 KB");
    expect(formatByteSize(3.4 * 1024 * 1024)).toBe("3.4 MB");
    expect(formatByteSize(2.5 * 1024 ** 3)).toBe("2.5 GB");
  });

  it("handles invalid input", () => {
    expect(formatByteSize(-5)).toBe("0 B");
    expect(formatByteSize(Number.NaN)).toBe("0 B");
  });
});

describe("fileKindLabel", () => {
  it("maps known kinds to labels", () => {
    expect(fileKindLabel("markdown")).toBe("Markdown");
    expect(fileKindLabel("code")).toBe("Code");
    expect(fileKindLabel("html")).toBe("HTML");
    expect(fileKindLabel("image")).toBe("Image");
    expect(fileKindLabel("notebook")).toBe("Notebook");
    expect(fileKindLabel("data")).toBe("Data");
  });

  it("falls back to File for unknown kinds", () => {
    expect(fileKindLabel("other")).toBe("File");
    expect(fileKindLabel("mystery")).toBe("File");
  });
});
