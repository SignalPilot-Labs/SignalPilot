import type { ConversationFileInfo } from "~/lib/api";

/**
 * Resolves markdown image and link references against the conversation
 * file manifest. The agent writes `![caption](artifacts/x.png)` or an
 * absolute sandbox path; the renderer maps either to a manifest row.
 *
 * Pure functions: unit tested, no React, no fetch.
 */

/**
 * Sentinel origin the markdown sanitizer resolves bare relative targets
 * against. rehype-harden drops a target it cannot parse as a URL, and
 * `artifacts/x.png` is not one; with this `defaultOrigin` it survives as
 * `https://conversation-files.invalid/artifacts/x.png`, which the resolver
 * strips back to `artifacts/x.png`. The `.invalid` TLD never resolves, so a
 * reference that escapes the resolver cannot reach a real host.
 */
export const FILE_REF_ORIGIN = "https://conversation-files.invalid";

/** `http:`, `https:`, `data:`, `blob:`, `mailto:` and any other scheme. */
const SCHEME_RE = /^[a-z][a-z0-9+.-]*:/i;

/** The scratch root of one run inside the sandbox. */
const RUN_ROOT_RE = /signalpilot-chat-runs\/[^/]+\/(.+)$/;

/**
 * Normalize a `src` or `href` into a manifest-shaped relative path.
 * Returns null for anything with a scheme (not a file reference).
 *
 * - Query string and fragment are dropped; percent-escapes are decoded.
 * - An absolute path keeps the tail after the run segment
 *   (`/tmp/signalpilot-chat-runs/<run>/artifacts/x.png` -> `artifacts/x.png`)
 *   or after the last `/artifacts/`; any other absolute path keeps only
 *   its basename.
 * - Leading `./`, `../` and `/` are stripped.
 */
export function normalizeFileRef(src: string | null | undefined): string | null {
  if (typeof src !== "string") return null;
  let value = src.trim();
  if (!value) return null;
  const sentinel = value.startsWith(`${FILE_REF_ORIGIN}/`);
  if (sentinel) value = value.slice(FILE_REF_ORIGIN.length + 1);
  if (SCHEME_RE.test(value) || value.startsWith("//")) return null;
  value = value.split(/[?#]/, 1)[0] ?? "";
  try {
    value = decodeURIComponent(value);
  } catch {
    // Keep the raw form when the escapes are malformed.
  }
  value = value.replace(/\\/g, "/");
  // A sentinel-origin target was a bare relative path; keep its directory.
  if (!sentinel && value.startsWith("/")) {
    const runMatch = RUN_ROOT_RE.exec(value);
    const artifactsIndex = value.lastIndexOf("/artifacts/");
    if (runMatch) {
      value = runMatch[1];
    } else if (artifactsIndex >= 0) {
      value = value.slice(artifactsIndex + 1);
    } else {
      value = value.split("/").pop() ?? "";
    }
  }
  value = value.replace(/^(?:\.\.?\/|\/)+/, "").replace(/\/\.\//g, "/");
  return value || null;
}

/** Last path segment of a normalized reference. */
export function fileRefBasename(norm: string): string {
  return norm.split("/").pop() ?? norm;
}

/** True when a manifest path matches a normalized reference. Mirrors the
 * first three resolution rules for a single path with no manifest. */
export function pathMatchesRef(path: string, norm: string): boolean {
  return (
    path === norm ||
    path === `artifacts/${norm}` ||
    path.endsWith(`/${norm}`)
  );
}

/**
 * Resolve a normalized reference to one active manifest row, in order:
 *
 * 1. `path === norm`
 * 2. `path === "artifacts/" + norm`
 * 3. exactly one path ending with `"/" + norm` (legacy rows carry a
 *    `<run_id>/artifacts/x.png` prefix and resolve here)
 * 4. rows whose `filename` is the basename of `norm`, preferring the
 *    running run's own file, then the newest `updated_at`
 *
 * Returns null when nothing matches; the caller decides between pending
 * and missing.
 */
export function resolveFileRef(
  norm: string | null,
  files: readonly ConversationFileInfo[],
  options: { runId?: string | null } = {},
): ConversationFileInfo | null {
  if (!norm) return null;
  const active = files.filter((file) => file.status === "active");
  const exact = active.find((file) => file.path === norm);
  if (exact) return exact;
  const underArtifacts = active.find(
    (file) => file.path === `artifacts/${norm}`,
  );
  if (underArtifacts) return underArtifacts;
  const suffixMatches = active.filter((file) => file.path.endsWith(`/${norm}`));
  if (suffixMatches.length === 1) return suffixMatches[0];
  const basename = fileRefBasename(norm);
  const byName = active.filter((file) => file.filename === basename);
  if (byName.length === 0) return null;
  const runId = options.runId ?? null;
  const ranked = [...byName].sort((a, b) => {
    const aOwn = runId && a.origin_run_id === runId ? 1 : 0;
    const bOwn = runId && b.origin_run_id === runId ? 1 : 0;
    if (aOwn !== bOwn) return bOwn - aOwn;
    return b.updated_at.localeCompare(a.updated_at);
  });
  return ranked[0];
}

/** `![alt](src "title")` and `[label](href)`. Angle-bracketed targets and
 * an optional quoted title are accepted. */
const MARKDOWN_TARGET_RE =
  /!?\[[^\]]*\]\(\s*(?:<([^>]*)>|([^\s<>()]+))(?:\s+(?:"[^"]*"|'[^']*'|\([^)]*\)))?\s*\)/g;

/** `<img src="…">` and `<a href="…">` in raw HTML. */
const HTML_TARGET_RE =
  /<(?:img|a)\b[^>]*?\b(?:src|href)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))/gi;

/**
 * Every normalized file reference in a markdown string: images, links,
 * raw `<img>` and `<a>`. External targets are dropped. Deduplicated,
 * in document order.
 */
export function collectFileRefs(markdown: string): string[] {
  if (!markdown) return [];
  const refs = new Set<string>();
  for (const match of markdown.matchAll(MARKDOWN_TARGET_RE)) {
    const norm = normalizeFileRef(match[1] ?? match[2]);
    if (norm) refs.add(norm);
  }
  for (const match of markdown.matchAll(HTML_TARGET_RE)) {
    const norm = normalizeFileRef(match[1] ?? match[2] ?? match[3]);
    if (norm) refs.add(norm);
  }
  return [...refs];
}
