import { describe, expect, it } from "vitest";
import type { ConversationFileInfo, ConversationNotebook } from "~/lib/api";
import {
  EMPTY_ARTIFACT_NOTICE_LEDGER,
  MAX_VISIBLE_ARTIFACT_NOTICES,
  appendArtifactNotices,
  deriveArtifactNotices,
  type ArtifactNotice,
} from "~/lib/chat-artifact-notices";

function notebook(status: ConversationNotebook["status"]): ConversationNotebook {
  return {
    name: "analysis",
    status,
    gateway_session_id: null,
    kernel_session_id: null,
    notebook_path: null,
    document: null,
  };
}

function file(
  id: string,
  kind: ConversationFileInfo["kind"],
): ConversationFileInfo {
  return {
    id,
    path: `artifacts/${id}`,
    filename: id,
    kind,
    mime_type: null,
    byte_size: 1,
    content_hash: id,
    origin_run_id: "run-1",
    origin: "runtime",
    status: "active",
    created_at: "2026-09-22T00:00:00Z",
    updated_at: "2026-09-22T00:00:00Z",
  };
}

describe("deriveArtifactNotices", () => {
  it("announces the default notebook going live once per run", () => {
    const first = deriveArtifactNotices({
      notebooks: [notebook("live")],
      files: [],
      currentRunId: "run-1",
      ledger: EMPTY_ARTIFACT_NOTICE_LEDGER,
      seedFiles: false,
    });
    expect(first.notices.map((n) => n.id)).toEqual(["notebook:run-1"]);
    expect(first.notices[0].target).toEqual({ kind: "notebook" });
    const again = deriveArtifactNotices({
      notebooks: [notebook("live")],
      files: [],
      currentRunId: "run-1",
      ledger: first.ledger,
      seedFiles: false,
    });
    expect(again.notices).toEqual([]);
    expect(again.ledger).toBe(first.ledger);
    // A later run's notebook is news again.
    const nextRun = deriveArtifactNotices({
      notebooks: [notebook("live")],
      files: [],
      currentRunId: "run-2",
      ledger: again.ledger,
      seedFiles: false,
    });
    expect(nextRun.notices.map((n) => n.id)).toEqual(["notebook:run-2"]);
  });

  it("stays quiet for an ended notebook or with no run in flight", () => {
    for (const [notebooks, runId] of [
      [[notebook("ended")], "run-1"],
      [[notebook("live")], undefined],
    ] as const) {
      const result = deriveArtifactNotices({
        notebooks: [...notebooks],
        files: [],
        currentRunId: runId,
        ledger: EMPTY_ARTIFACT_NOTICE_LEDGER,
        seedFiles: false,
      });
      expect(result.notices).toEqual([]);
    }
  });

  it("announces charts, dashboards and reports but not code, data or notes", () => {
    const result = deriveArtifactNotices({
      notebooks: [],
      files: [
        file("q3.py", "code"),
        file("chart.png", "image"),
        file("rows.csv", "data"),
        file("board.dashboard.json", "dashboard"),
        file("notes.md", "markdown"),
        file("report.html", "html"),
      ],
      currentRunId: "run-1",
      ledger: EMPTY_ARTIFACT_NOTICE_LEDGER,
      seedFiles: false,
    });
    expect(result.notices.map((n) => [n.kind, n.detail])).toEqual([
      ["chart", "chart.png"],
      ["dashboard", "board.dashboard.json"],
      ["report", "report.html"],
    ]);
    expect(result.notices[0].target).toEqual({
      kind: "file",
      fileId: "chart.png",
    });
    // Silent kinds are still recorded, so they are never re-evaluated.
    expect(result.ledger.files.size).toBe(6);
  });

  it("seeds the first manifest silently and announces only later files", () => {
    const seeded = deriveArtifactNotices({
      notebooks: [],
      files: [file("old.png", "image")],
      currentRunId: "run-1",
      ledger: EMPTY_ARTIFACT_NOTICE_LEDGER,
      seedFiles: true,
    });
    expect(seeded.notices).toEqual([]);
    const later = deriveArtifactNotices({
      notebooks: [],
      files: [file("old.png", "image"), file("new.png", "image")],
      currentRunId: "run-1",
      ledger: seeded.ledger,
      seedFiles: false,
    });
    expect(later.notices.map((n) => n.id)).toEqual(["file:new.png"]);
  });
});

describe("appendArtifactNotices", () => {
  const notice = (id: string): ArtifactNotice => ({
    id,
    kind: "chart",
    title: "The agent generated a chart",
    detail: id,
    target: { kind: "file", fileId: id },
  });

  it("keeps the newest few and drops duplicates", () => {
    const stack = appendArtifactNotices(
      [notice("a"), notice("b")],
      [notice("b"), notice("c"), notice("d")],
    );
    expect(stack.map((n) => n.id)).toEqual(["b", "c", "d"]);
    expect(stack).toHaveLength(MAX_VISIBLE_ARTIFACT_NOTICES);
  });

  it("returns the same array when nothing is added", () => {
    const visible = [notice("a")];
    expect(appendArtifactNotices(visible, [])).toBe(visible);
  });
});
