import type {
  ConversationFileInfo,
  ConversationFileKind,
  StandaloneChatEvent,
} from "~/lib/api";

/**
 * Derives the inline artifact cards for one chat run.
 *
 * Cards are computed client-side from two sources the page already has:
 * the run's event stream (Write/Edit tool calls anchor a card's position)
 * and the gateway's conversation file manifest (the single source of truth
 * for what actually exists). No new gateway event type is involved.
 *
 * Pure and synchronous so it can be unit tested and replayed on the
 * fixture page.
 */

export type ArtifactCardState =
  /** The manifest row exists — the card represents the current file. */
  | "ready"
  /** A write happened but the mirror hasn't confirmed the file yet. */
  | "pending"
  /** The run ended and the file never materialized. */
  | "unfinished";

export type ArtifactCardModel = {
  /** Stable key: one card per file path per run. */
  key: string;
  path: string;
  filename: string;
  kind: ConversationFileKind;
  state: ArtifactCardState;
  /** The manifest row; null unless state is "ready". */
  file: ConversationFileInfo | null;
  /** True when the file changed after its first write. */
  updated: boolean;
  /** Write/Edit tool calls observed for this path in the run. */
  writeCount: number;
  /** Anchor order within the run (first write sequence; manifest-only last). */
  sequence: number;
  /** ISO timestamp of the last observed change. */
  lastTouchedAt: string;
};

/** Tools whose calls create or change files the worker mirrors. */
const WRITE_TOOLS = new Set(["Write", "NotebookEdit"]);
const EDIT_TOOLS = new Set(["Edit", "MultiEdit"]);

const text = (value: unknown): string | null =>
  typeof value === "string" && value.trim() ? value : null;

/** Match a tool-call path against a manifest path. The manifest stores
 * workspace-relative paths; tool calls sometimes use absolute ones. A suffix
 * match is accepted only when it is unambiguous: an absolute tool path may
 * end with a relative manifest path at a `/` boundary. Two relative paths
 * never suffix-match (`archive/report.html` is NOT `report.html` — merging
 * them would make the card lie on click). Callers should still prefer an
 * exact match before falling back to this. */
export function pathsMatch(a: string, b: string): boolean {
  if (a === b) return true;
  if (a.startsWith("/") && !b.startsWith("/")) return a.endsWith(`/${b}`);
  if (b.startsWith("/") && !a.startsWith("/")) return b.endsWith(`/${a}`);
  return false;
}

/** Mirror the manifest's noise filter so no phantom pending card appears
 * for a file the mirror will never list. */
export function isMirroredPath(path: string): boolean {
  const segments = path.split("/").filter(Boolean);
  if (segments.length === 0) return false;
  if (segments.some((part) => part.startsWith(".") || part === "__pycache__")) {
    return false;
  }
  // Top-level *.py files are notebooks; the notebook flow covers them.
  if (segments.length === 1 && /\.py$/i.test(segments[0])) return false;
  return true;
}

/** Guess a manifest kind from a path — used only for pending cards. */
export function guessKindFromPath(path: string): ConversationFileKind {
  const ext = /\.([a-z0-9]+)$/i.exec(path)?.[1]?.toLowerCase() ?? "";
  if (["md", "mdx", "markdown"].includes(ext)) return "markdown";
  if (["html", "htm"].includes(ext)) return "html";
  if (["png", "jpg", "jpeg", "gif", "svg", "webp"].includes(ext))
    return "image";
  if (ext === "ipynb") return "notebook";
  if (["csv", "tsv", "parquet", "json", "jsonl", "xlsx"].includes(ext))
    return "data";
  if (["py", "sql", "js", "ts", "sh", "r", "rs", "go", "yml", "yaml"].includes(ext))
    return "code";
  return "other";
}

type PathTouch = {
  path: string;
  firstSequence: number;
  count: number;
  lastAt: string;
};

function collectTouches(
  events: StandaloneChatEvent[],
  runId: string,
): PathTouch[] {
  const byPath = new Map<string, PathTouch>();
  const sorted = events
    .filter((event) => event.run_id === runId && event.type === "tool_started")
    .sort((a, b) => a.sequence - b.sequence);
  for (const event of sorted) {
    const tool = text(event.payload.tool);
    if (!tool || (!WRITE_TOOLS.has(tool) && !EDIT_TOOLS.has(tool))) continue;
    const input =
      typeof event.payload.input === "object" && event.payload.input !== null
        ? (event.payload.input as Record<string, unknown>)
        : null;
    const path =
      text(input?.file_path) ?? text(input?.notebook_path) ?? text(input?.path);
    if (!path || !isMirroredPath(path)) continue;
    const touches = [...byPath.values()];
    // Exact match first; the suffix rule only bridges absolute↔relative.
    const existing =
      touches.find((touch) => touch.path === path) ??
      touches.find((touch) => pathsMatch(touch.path, path));
    if (existing) {
      existing.count += 1;
      existing.lastAt = event.created_at;
    } else {
      byPath.set(path, {
        path,
        firstSequence: event.sequence,
        count: 1,
        lastAt: event.created_at,
      });
    }
  }
  return [...byPath.values()];
}

/**
 * One card per file path per run. Ready cards come from the manifest
 * (every active file whose origin is this run); a write the mirror hasn't
 * confirmed yet renders pending while the run streams and collapses to a
 * quiet stub once the run is over.
 */
export function deriveArtifactCards(
  events: StandaloneChatEvent[],
  files: ConversationFileInfo[],
  runId: string,
  running: boolean,
): ArtifactCardModel[] {
  if (!runId) return [];
  const touches = collectTouches(events, runId);
  const runFiles = files.filter(
    (file) => file.status === "active" && file.origin_run_id === runId,
  );
  const cards: ArtifactCardModel[] = [];
  const matchedTouches = new Set<PathTouch>();

  for (const file of runFiles) {
    const touch =
      touches.find((entry) => entry.path === file.path) ??
      touches.find((entry) => pathsMatch(entry.path, file.path));
    if (touch) matchedTouches.add(touch);
    const editedInPlace =
      (touch?.count ?? 0) > 1 || file.updated_at > file.created_at;
    const lastAt =
      touch && touch.lastAt > file.updated_at ? touch.lastAt : file.updated_at;
    cards.push({
      key: `card-${runId}-${file.path}`,
      path: file.path,
      filename: file.filename,
      kind: file.kind,
      state: "ready",
      file,
      updated: editedInPlace,
      writeCount: touch?.count ?? 0,
      sequence: touch?.firstSequence ?? Number.MAX_SAFE_INTEGER,
      lastTouchedAt: lastAt,
    });
  }

  for (const touch of touches) {
    if (matchedTouches.has(touch)) continue;
    cards.push({
      key: `card-${runId}-${touch.path}`,
      path: touch.path,
      filename: touch.path.split("/").pop() ?? touch.path,
      kind: guessKindFromPath(touch.path),
      state: running ? "pending" : "unfinished",
      file: null,
      updated: false,
      writeCount: touch.count,
      sequence: touch.firstSequence,
      lastTouchedAt: touch.lastAt,
    });
  }

  return cards.sort((a, b) => {
    if (a.sequence !== b.sequence) return a.sequence - b.sequence;
    const aCreated = a.file?.created_at ?? a.lastTouchedAt;
    const bCreated = b.file?.created_at ?? b.lastTouchedAt;
    return aCreated < bCreated ? -1 : aCreated > bCreated ? 1 : 0;
  });
}

/**
 * Drop cards already covered by a richer surface in the same message —
 * the legacy published-artifact previews (table/chart/report). One file must
 * never render twice, back to back, with different verbs (design review #5).
 * Matches by exact filename or full path; `q3_growth_by_region.vl.json`
 * does not cover `q3_growth_by_region.svg`.
 */
export function suppressCoveredCards(
  cards: ArtifactCardModel[],
  coveredFilenames: readonly string[],
): ArtifactCardModel[] {
  if (coveredFilenames.length === 0) return cards;
  const covered = new Set(coveredFilenames.filter(Boolean));
  return cards.filter(
    (card) => !covered.has(card.filename) && !covered.has(card.path),
  );
}

/** Plain-English type label. Never repeats what the extension already says
 * next to it in the filename (say-it-once rule). */
export function cardKindLabel(kind: string, filename: string): string {
  const ext = /\.([a-z0-9]+)$/i.exec(filename)?.[1]?.toLowerCase() ?? "";
  switch (kind) {
    case "html":
      return "Report";
    case "image":
      return "Image";
    case "data":
      if (ext === "csv" || ext === "tsv") return "CSV export";
      if (ext === "json" || ext === "jsonl") return "JSON export";
      return "Data export";
    case "markdown":
      return "Document";
    case "notebook":
      return "Notebook";
    case "code":
      if (ext === "sql") return "SQL query";
      if (ext === "py") return "Script";
      return "Code";
    default:
      return "File";
  }
}

/** Primary action verb by kind — plain verbs that name the outcome. */
export function primaryActionLabel(kind: string): string {
  switch (kind) {
    case "html":
    case "image":
      return "Open";
    case "data":
      return "Preview";
    case "markdown":
      return "Read";
    default:
      return "View";
  }
}

/** Middle-truncate so both the stem and the extension stay visible. */
export function middleTruncate(value: string, max = 44): string {
  if (value.length <= max) return value;
  const keep = max - 1;
  const head = Math.ceil(keep * 0.62);
  const tail = keep - head;
  return `${value.slice(0, head)}…${value.slice(value.length - tail)}`;
}

/** Coarse relative label, e.g. "just now" or "2m ago". `now` is injectable
 * so tests stay deterministic. */
export function relativeTimeLabel(iso: string, now = Date.now()): string {
  const then = Date.parse(iso);
  if (!Number.isFinite(then)) return "";
  const seconds = Math.max(0, Math.round((now - then) / 1000));
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86_400) return `${Math.round(seconds / 3600)}h ago`;
  return `${Math.round(seconds / 86_400)}d ago`;
}
