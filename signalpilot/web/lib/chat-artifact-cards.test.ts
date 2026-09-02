import { describe, expect, it } from "vitest";
import type { ConversationFileInfo, StandaloneChatEvent } from "~/lib/api";
import {
  cardKindLabel,
  deriveArtifactCards,
  guessKindFromPath,
  isMirroredPath,
  middleTruncate,
  pathsMatch,
  primaryActionLabel,
  relativeTimeLabel,
  suppressReferencedCards,
} from "./chat-artifact-cards";

const RUN = "run-1";

let sequenceCounter = 0;

function writeEvent(
  path: string,
  options: { tool?: string; runId?: string; at?: string; sequence?: number } = {},
): StandaloneChatEvent {
  sequenceCounter += 1;
  return {
    run_id: options.runId ?? RUN,
    sequence: options.sequence ?? sequenceCounter,
    type: "tool_started",
    payload: {
      tool: options.tool ?? "Write",
      input: { file_path: path, content: "x" },
    },
    created_at: options.at ?? "2026-01-15T17:30:00.000Z",
  } as StandaloneChatEvent;
}

function file(
  path: string,
  overrides: Partial<ConversationFileInfo> = {},
): ConversationFileInfo {
  return {
    id: `id-${path}`,
    path,
    filename: path.split("/").pop() ?? path,
    kind: guessKindFromPath(path),
    mime_type: null,
    byte_size: 128,
    content_hash: "hash-1",
    origin_run_id: RUN,
    origin: "mirror",
    status: "active",
    created_at: "2026-01-15T17:30:05.000Z",
    updated_at: "2026-01-15T17:30:05.000Z",
    ...overrides,
  };
}

describe("deriveArtifactCards", () => {
  it("joins a write event to its manifest row as one ready card", () => {
    const cards = deriveArtifactCards(
      [writeEvent("exports/report.html", { sequence: 5 })],
      [file("exports/report.html")],
      RUN,
      true,
    );
    expect(cards).toHaveLength(1);
    expect(cards[0]).toMatchObject({
      state: "ready",
      path: "exports/report.html",
      filename: "report.html",
      kind: "html",
      updated: false,
      writeCount: 1,
      sequence: 5,
    });
    expect(cards[0].file?.id).toBe("id-exports/report.html");
  });

  it("renders a pending card while the mirror has not confirmed the file", () => {
    const cards = deriveArtifactCards(
      [writeEvent("exports/report.html")],
      [],
      RUN,
      true,
    );
    expect(cards).toHaveLength(1);
    expect(cards[0].state).toBe("pending");
    expect(cards[0].kind).toBe("html");
    expect(cards[0].file).toBeNull();
  });

  it("collapses an unconfirmed write to an unfinished stub once the run ends", () => {
    const cards = deriveArtifactCards(
      [writeEvent("exports/report.html")],
      [],
      RUN,
      false,
    );
    expect(cards[0].state).toBe("unfinished");
  });

  it("keeps one card per path across a write and later edits, marked updated", () => {
    const events = [
      writeEvent("analysis/calc.py", { sequence: 3 }),
      writeEvent("analysis/calc.py", { tool: "Edit", sequence: 9 }),
    ];
    const cards = deriveArtifactCards(
      events,
      [file("analysis/calc.py")],
      RUN,
      true,
    );
    expect(cards).toHaveLength(1);
    expect(cards[0].updated).toBe(true);
    expect(cards[0].writeCount).toBe(2);
    // Anchored at the FIRST write, not the edit.
    expect(cards[0].sequence).toBe(3);
  });

  it("marks a card updated when the manifest row changed after creation", () => {
    const cards = deriveArtifactCards(
      [writeEvent("a.csv", { sequence: 1 })],
      [
        file("a.csv", {
          created_at: "2026-01-15T17:30:05.000Z",
          updated_at: "2026-01-15T17:31:00.000Z",
        }),
      ],
      RUN,
      false,
    );
    expect(cards[0].state).toBe("ready");
    expect(cards[0].updated).toBe(true);
  });

  it("orders cards by first write sequence, manifest-only files last", () => {
    const events = [
      writeEvent("second.csv", { sequence: 20 }),
      writeEvent("first.html", { sequence: 10 }),
    ];
    const files = [
      file("second.csv"),
      file("first.html"),
      file("exports/from_bash.png", { created_at: "2026-01-15T17:32:00.000Z" }),
    ];
    const cards = deriveArtifactCards(events, files, RUN, false);
    expect(cards.map((card) => card.path)).toEqual([
      "first.html",
      "second.csv",
      "exports/from_bash.png",
    ]);
    // The bash-produced file still gets a ready card.
    expect(cards[2].state).toBe("ready");
  });

  it("orders multiple manifest-only files by creation time", () => {
    const files = [
      file("b.png", { created_at: "2026-01-15T17:32:00.000Z" }),
      file("a.png", { created_at: "2026-01-15T17:31:00.000Z" }),
    ];
    const cards = deriveArtifactCards([], files, RUN, false);
    expect(cards.map((card) => card.path)).toEqual(["a.png", "b.png"]);
  });

  it("excludes non-active manifest rows and other runs' files", () => {
    const files = [
      file("gone.csv", { status: "deleted" }),
      file("other.csv", { origin_run_id: "run-2" }),
    ];
    expect(deriveArtifactCards([], files, RUN, false)).toHaveLength(0);
  });

  it("ignores write events from other runs", () => {
    const cards = deriveArtifactCards(
      [writeEvent("exports/x.html", { runId: "run-2" })],
      [],
      RUN,
      true,
    );
    expect(cards).toHaveLength(0);
  });

  it("matches an absolute tool path against a relative manifest path", () => {
    const cards = deriveArtifactCards(
      [writeEvent("/workspace/exports/report.html", { sequence: 4 })],
      [file("exports/report.html")],
      RUN,
      true,
    );
    expect(cards).toHaveLength(1);
    expect(cards[0].state).toBe("ready");
    expect(cards[0].sequence).toBe(4);
  });

  it("never creates phantom cards for notebook and noise paths", () => {
    const events = [
      writeEvent("analysis.py"), // top-level *.py = notebook
      writeEvent(".env"),
      writeEvent("pkg/__pycache__/mod.pyc"),
    ];
    expect(deriveArtifactCards(events, [], RUN, true)).toHaveLength(0);
  });

  it("counts an edit that uses a path variant toward the same card", () => {
    const events = [
      writeEvent("exports/a.csv", { sequence: 1 }),
      writeEvent("/workspace/exports/a.csv", { tool: "Edit", sequence: 2 }),
    ];
    const cards = deriveArtifactCards(events, [file("exports/a.csv")], RUN, true);
    expect(cards).toHaveLength(1);
    expect(cards[0].writeCount).toBe(2);
  });

  it("keeps two files with ambiguously similar relative paths separate", () => {
    // A write to archive/report.html must NOT join the manifest row for
    // report.html — that card would lie on click (wrong bytes and hash).
    const cards = deriveArtifactCards(
      [writeEvent("archive/report.html", { sequence: 2 })],
      [file("report.html")],
      RUN,
      true,
    );
    expect(cards).toHaveLength(2);
    const ready = cards.find((card) => card.state === "ready");
    const pending = cards.find((card) => card.state === "pending");
    expect(ready?.path).toBe("report.html");
    expect(pending?.path).toBe("archive/report.html");
  });

  it("prefers an exact path match over an absolute-suffix match", () => {
    const events = [
      writeEvent("/workspace/exports/a.csv", { sequence: 1 }),
      writeEvent("exports/a.csv", { sequence: 2 }),
    ];
    const cards = deriveArtifactCards(events, [file("exports/a.csv")], RUN, true);
    expect(cards).toHaveLength(1);
    expect(cards[0].writeCount).toBe(2);
  });

  it("returns nothing for an empty run id", () => {
    expect(deriveArtifactCards([], [file("a.csv")], "", true)).toHaveLength(0);
  });

  it("rehydrates identically from persisted events regardless of event order", () => {
    const events = [
      writeEvent("b.csv", { sequence: 8 }),
      writeEvent("a.html", { sequence: 2 }),
    ];
    const files = [file("a.html"), file("b.csv")];
    const live = deriveArtifactCards(events, files, RUN, false);
    const rehydrated = deriveArtifactCards(
      [...events].reverse(),
      [...files].reverse(),
      RUN,
      false,
    );
    expect(rehydrated).toEqual(live);
  });
});

describe("helpers", () => {
  it("pathsMatch handles exact, absolute-suffix, and non-matches", () => {
    expect(pathsMatch("a/b.csv", "a/b.csv")).toBe(true);
    expect(pathsMatch("/w/a/b.csv", "a/b.csv")).toBe(true);
    expect(pathsMatch("a/b.csv", "/w/a/b.csv")).toBe(true);
    expect(pathsMatch("xa/b.csv", "a/b.csv")).toBe(false);
    expect(pathsMatch("a/b.csv", "a/c.csv")).toBe(false);
    // Boundary check even for the absolute case.
    expect(pathsMatch("/wa/b.csv", "a/b.csv")).toBe(false);
  });

  it("pathsMatch never merges two distinct relative paths by suffix", () => {
    // archive/report.html and report.html are different files; matching
    // them would show one file's metadata over another's content.
    expect(pathsMatch("archive/report.html", "report.html")).toBe(false);
    expect(pathsMatch("report.html", "archive/report.html")).toBe(false);
  });

  it("isMirroredPath mirrors the manifest noise filter", () => {
    expect(isMirroredPath("exports/report.html")).toBe(true);
    expect(isMirroredPath("nested/analysis.py")).toBe(true);
    expect(isMirroredPath("analysis.py")).toBe(false);
    expect(isMirroredPath(".gitignore")).toBe(false);
    expect(isMirroredPath("a/__pycache__/b.pyc")).toBe(false);
    expect(isMirroredPath("")).toBe(false);
  });

  it("guessKindFromPath maps common extensions", () => {
    expect(guessKindFromPath("a/report.html")).toBe("html");
    expect(guessKindFromPath("a/chart.svg")).toBe("image");
    expect(guessKindFromPath("a/data.csv")).toBe("data");
    expect(guessKindFromPath("a/notes.md")).toBe("markdown");
    expect(guessKindFromPath("a/calc.py")).toBe("code");
    expect(guessKindFromPath("a/book.ipynb")).toBe("notebook");
    expect(guessKindFromPath("a/blob.bin")).toBe("other");
    expect(guessKindFromPath("a/noext")).toBe("other");
  });

  it("cardKindLabel says it once, in plain words", () => {
    expect(cardKindLabel("html", "report.html")).toBe("Report");
    expect(cardKindLabel("data", "rows.csv")).toBe("CSV export");
    expect(cardKindLabel("data", "rows.json")).toBe("JSON export");
    expect(cardKindLabel("data", "rows.parquet")).toBe("Data export");
    expect(cardKindLabel("code", "query.sql")).toBe("SQL query");
    expect(cardKindLabel("code", "calc.py")).toBe("Script");
    expect(cardKindLabel("image", "chart.png")).toBe("Image");
    expect(cardKindLabel("notebook", "a.ipynb")).toBe("Notebook");
    expect(cardKindLabel("markdown", "notes.md")).toBe("Document");
    expect(cardKindLabel("other", "blob.bin")).toBe("File");
  });

  it("primaryActionLabel names the outcome per kind", () => {
    expect(primaryActionLabel("html")).toBe("Open");
    expect(primaryActionLabel("image")).toBe("Open");
    expect(primaryActionLabel("data")).toBe("Preview");
    expect(primaryActionLabel("markdown")).toBe("Read");
    expect(primaryActionLabel("code")).toBe("View");
    expect(primaryActionLabel("notebook")).toBe("View");
  });

  it("middleTruncate keeps the stem and the extension visible", () => {
    expect(middleTruncate("short.csv")).toBe("short.csv");
    const long = "q3_pipeline_breakdown_by_source_and_region_final.png";
    const truncated = middleTruncate(long, 30);
    expect(truncated.length).toBeLessThanOrEqual(30);
    expect(truncated).toContain("…");
    expect(truncated.startsWith("q3_pipeline")).toBe(true);
    expect(truncated.endsWith(".png")).toBe(true);
  });

  it("relativeTimeLabel is deterministic with an injected clock", () => {
    const base = Date.parse("2026-01-15T18:00:00.000Z");
    expect(relativeTimeLabel("2026-01-15T17:59:40.000Z", base)).toBe("just now");
    expect(relativeTimeLabel("2026-01-15T17:58:00.000Z", base)).toBe("2m ago");
    expect(relativeTimeLabel("2026-01-15T15:00:00.000Z", base)).toBe("3h ago");
    expect(relativeTimeLabel("2026-01-13T18:00:00.000Z", base)).toBe("2d ago");
    expect(relativeTimeLabel("not a date", base)).toBe("");
  });
});

describe("files_changed touch source", () => {
  function filesChanged(
    paths: string[],
    options: { sequence?: number; deleted?: boolean; toolCallId?: string } = {},
  ): StandaloneChatEvent {
    sequenceCounter += 1;
    return {
      run_id: RUN,
      sequence: options.sequence ?? sequenceCounter,
      type: "files_changed",
      payload: {
        changed: paths.length,
        files: paths.map((path) => ({
          file_id: `id-${path}`,
          path,
          filename: path.split("/").pop() ?? path,
          kind: guessKindFromPath(path),
          byte_size: 10,
          content_hash: "h",
          deleted: options.deleted ?? false,
        })),
        tool_call_id: options.toolCallId ?? "t1",
        origin: "runtime",
      },
      created_at: "2026-01-15T17:30:20.000Z",
    } as StandaloneChatEvent;
  }

  it("anchors a card at the files_changed sequence when no Write step exists", () => {
    const cards = deriveArtifactCards(
      [filesChanged(["artifacts/revenue.png"], { sequence: 40 })],
      [file("artifacts/revenue.png")],
      RUN,
      true,
    );
    expect(cards).toHaveLength(1);
    expect(cards[0]).toMatchObject({
      state: "ready",
      path: "artifacts/revenue.png",
      kind: "image",
      sequence: 40,
      writeCount: 1,
    });
  });

  it("renders a pending card for a captured file the manifest has not listed yet", () => {
    const cards = deriveArtifactCards(
      [filesChanged(["artifacts/revenue.png"])],
      [],
      RUN,
      true,
    );
    expect(cards[0].state).toBe("pending");
  });

  it("ignores deleted entries and the legacy content-free payload", () => {
    const legacy = {
      run_id: RUN,
      sequence: 3,
      type: "files_changed",
      payload: { changed: ["artifacts/old.png"], deleted: [] },
      created_at: "2026-01-15T17:30:20.000Z",
    } as StandaloneChatEvent;
    const cards = deriveArtifactCards(
      [legacy, filesChanged(["artifacts/gone.png"], { deleted: true })],
      [],
      RUN,
      true,
    );
    expect(cards).toEqual([]);
  });

  it("counts a Write and its capture event as one touch group", () => {
    const cards = deriveArtifactCards(
      [
        writeEvent("exports/report.html", { sequence: 5 }),
        filesChanged(["exports/report.html"], { sequence: 7 }),
      ],
      [file("exports/report.html")],
      RUN,
      true,
    );
    expect(cards).toHaveLength(1);
    expect(cards[0].sequence).toBe(5);
    expect(cards[0].writeCount).toBe(2);
  });

  it("no longer treats NotebookEdit as a write", () => {
    const cards = deriveArtifactCards(
      [writeEvent("analysis.py", { tool: "NotebookEdit" })],
      [],
      RUN,
      true,
    );
    expect(cards).toEqual([]);
  });
});

describe("suppressReferencedCards", () => {
  const ready = (path: string) =>
    deriveArtifactCards([writeEvent(path)], [file(path)], RUN, true)[0];
  const pending = (path: string) =>
    deriveArtifactCards([writeEvent(path)], [], RUN, true)[0];

  it("drops cards the message body references inline", () => {
    const cards = [
      ready("artifacts/revenue.png"),
      ready("artifacts/rows.csv"),
      ready("exports/report.html"),
    ];
    const kept = suppressReferencedCards(
      cards,
      "![Revenue](artifacts/revenue.png)\n\n[rows](rows.csv)",
    );
    expect(kept.map((card) => card.path)).toEqual(["exports/report.html"]);
  });

  it("keeps every card when nothing is referenced", () => {
    const cards = [ready("artifacts/revenue.png")];
    expect(suppressReferencedCards(cards, "plain text")).toBe(cards);
    expect(suppressReferencedCards(cards, "")).toBe(cards);
  });

  it("matches pending cards on their path", () => {
    const cards = [pending("artifacts/revenue.png"), pending("exports/x.md")];
    const kept = suppressReferencedCards(
      cards,
      "![Revenue](/tmp/signalpilot-chat-runs/run-1/artifacts/revenue.png)",
    );
    expect(kept.map((card) => card.path)).toEqual(["exports/x.md"]);
  });

  it("ignores external references", () => {
    const cards = [ready("artifacts/revenue.png")];
    expect(
      suppressReferencedCards(cards, "![x](https://cdn/revenue.png)"),
    ).toHaveLength(1);
  });
});
