import { describe, expect, it } from "vitest";
import type { ConversationFileInfo } from "~/lib/api";
import {
  collectFileRefs,
  fileRefBasename,
  normalizeFileRef,
  pathMatchesRef,
  resolveFileRef,
} from "./chat-file-refs";

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
    byte_size: 10,
    content_hash: "h1",
    origin_run_id: "run-1",
    origin: "runtime",
    status: "active",
    created_at: "2026-01-15T17:30:00.000Z",
    updated_at: "2026-01-15T17:30:00.000Z",
    ...overrides,
  };
}

describe("normalizeFileRef", () => {
  it("returns null for any scheme", () => {
    for (const src of [
      "http://x/y.png",
      "https://x/y.png",
      "data:image/png;base64,AAAA",
      "blob:http://localhost/abc",
      "mailto:a@b.c",
      "sandbox://artifacts/x.png",
      "//cdn/x.png",
    ]) {
      expect(normalizeFileRef(src)).toBeNull();
    }
  });

  it("returns null for empty or non-string input", () => {
    expect(normalizeFileRef("")).toBeNull();
    expect(normalizeFileRef("   ")).toBeNull();
    expect(normalizeFileRef(undefined)).toBeNull();
    expect(normalizeFileRef(null)).toBeNull();
  });

  it("keeps a relative artifacts path as is", () => {
    expect(normalizeFileRef("artifacts/x.png")).toBe("artifacts/x.png");
    expect(normalizeFileRef("x.png")).toBe("x.png");
  });

  it("strips leading ./ ../ and /", () => {
    expect(normalizeFileRef("./artifacts/x.png")).toBe("artifacts/x.png");
    expect(normalizeFileRef("../artifacts/x.png")).toBe("artifacts/x.png");
    expect(normalizeFileRef("/x.png")).toBe("x.png");
    expect(normalizeFileRef("artifacts/./x.png")).toBe("artifacts/x.png");
  });

  it("strips query and fragment and decodes escapes", () => {
    expect(normalizeFileRef("artifacts/x.png?v=2#top")).toBe("artifacts/x.png");
    expect(normalizeFileRef("artifacts/revenue%20by%20month.png")).toBe(
      "artifacts/revenue by month.png",
    );
    // Malformed escapes keep the raw form instead of throwing.
    expect(normalizeFileRef("artifacts/x%E0.png")).toBe("artifacts/x%E0.png");
  });

  it("keeps the tail after the run segment of an absolute sandbox path", () => {
    expect(
      normalizeFileRef(
        "/tmp/signalpilot-chat-runs/run-abc/artifacts/x.png",
      ),
    ).toBe("artifacts/x.png");
    expect(
      normalizeFileRef("/var/tmp/signalpilot-chat-runs/run-abc/exports/r.html"),
    ).toBe("exports/r.html");
    expect(
      normalizeFileRef("/tmp/signalpilot-chat-runs/run-abc/artifacts/sub/y.png"),
    ).toBe("artifacts/sub/y.png");
  });

  it("keeps the tail after /artifacts/ for other absolute paths", () => {
    expect(normalizeFileRef("/home/agent/work/artifacts/x.png")).toBe(
      "artifacts/x.png",
    );
  });

  it("keeps only the basename for any other absolute path", () => {
    expect(normalizeFileRef("/home/agent/x.png")).toBe("x.png");
    expect(normalizeFileRef("/x.png")).toBe("x.png");
  });

  it("strips the sanitizer's sentinel origin and keeps the directory", () => {
    expect(
      normalizeFileRef("https://conversation-files.invalid/artifacts/x.png"),
    ).toBe("artifacts/x.png");
    expect(
      normalizeFileRef("https://conversation-files.invalid/exports/r.html?x=1"),
    ).toBe("exports/r.html");
    // A different host is external.
    expect(normalizeFileRef("https://conversation-files.example/x.png")).toBeNull();
  });

  it("normalizes backslashes", () => {
    expect(normalizeFileRef("artifacts\\x.png")).toBe("artifacts/x.png");
  });
});

describe("resolveFileRef", () => {
  it("returns null for null or unmatched references", () => {
    expect(resolveFileRef(null, [file("artifacts/x.png")])).toBeNull();
    expect(resolveFileRef("nope.png", [file("artifacts/x.png")])).toBeNull();
  });

  it("ignores deleted rows", () => {
    expect(
      resolveFileRef("artifacts/x.png", [
        file("artifacts/x.png", { status: "deleted" }),
      ]),
    ).toBeNull();
  });

  it("matches the exact path first", () => {
    const exact = file("artifacts/x.png");
    const other = file("legacy/artifacts/x.png");
    expect(resolveFileRef("artifacts/x.png", [other, exact])).toBe(exact);
  });

  it("matches a bare filename under artifacts/", () => {
    const row = file("artifacts/x.png");
    expect(resolveFileRef("x.png", [row])).toBe(row);
  });

  it("matches a unique suffix (legacy run-prefixed rows)", () => {
    const legacy = file("run-abc/artifacts/x.png");
    expect(resolveFileRef("artifacts/x.png", [legacy])).toBe(legacy);
  });

  it("falls through an ambiguous suffix to the filename rule", () => {
    const older = file("run-a/artifacts/x.png", {
      origin_run_id: "run-a",
      updated_at: "2026-01-15T17:00:00.000Z",
    });
    const newer = file("run-b/artifacts/x.png", {
      origin_run_id: "run-b",
      updated_at: "2026-01-15T18:00:00.000Z",
    });
    expect(resolveFileRef("artifacts/x.png", [older, newer])).toBe(newer);
  });

  it("prefers the running run's file over a newer one from another run", () => {
    const own = file("exports/x.png", {
      origin_run_id: "run-1",
      updated_at: "2026-01-15T17:00:00.000Z",
    });
    const foreign = file("other/x.png", {
      origin_run_id: "run-9",
      updated_at: "2026-01-15T19:00:00.000Z",
    });
    expect(
      resolveFileRef("x.png", [foreign, own], { runId: "run-1" }),
    ).toBe(own);
    // Without a running run, recency wins.
    expect(resolveFileRef("x.png", [foreign, own])).toBe(foreign);
  });

  it("matches by basename when the directory differs", () => {
    const row = file("charts/x.png");
    expect(resolveFileRef("images/x.png", [row])).toBe(row);
  });
});

describe("collectFileRefs", () => {
  it("collects images, links, raw img and a tags, deduplicated", () => {
    const markdown = [
      "Text ![Revenue](artifacts/revenue.png) and",
      '[Download](artifacts/rows.csv "the rows")',
      "![again](./artifacts/revenue.png)",
      '<img src="/tmp/signalpilot-chat-runs/run-1/artifacts/other.png" alt="x">',
      "<a href='exports/report.html'>report</a>",
      "[ext](https://example.com/x.png) ![data](data:image/png;base64,AA)",
      "[angle](<artifacts/spaced name.csv>)",
    ].join("\n");
    expect(collectFileRefs(markdown)).toEqual([
      "artifacts/revenue.png",
      "artifacts/rows.csv",
      "artifacts/spaced name.csv",
      "artifacts/other.png",
      "exports/report.html",
    ]);
  });

  it("returns an empty list for empty or reference-free markdown", () => {
    expect(collectFileRefs("")).toEqual([]);
    expect(collectFileRefs("plain **text**")).toEqual([]);
  });
});

describe("helpers", () => {
  it("fileRefBasename returns the last segment", () => {
    expect(fileRefBasename("artifacts/x.png")).toBe("x.png");
    expect(fileRefBasename("x.png")).toBe("x.png");
  });

  it("pathMatchesRef mirrors the path rules", () => {
    expect(pathMatchesRef("artifacts/x.png", "artifacts/x.png")).toBe(true);
    expect(pathMatchesRef("artifacts/x.png", "x.png")).toBe(true);
    expect(pathMatchesRef("run/artifacts/x.png", "artifacts/x.png")).toBe(true);
    expect(pathMatchesRef("artifacts/y.png", "x.png")).toBe(false);
  });
});
