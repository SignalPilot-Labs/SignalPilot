/**
 * Pure helpers for lineage navigation: model-ref resolution (deep links),
 * fuzzy not-found suggestions, staged column assignment for focus mode, and
 * the deduplicated raw-source rollup behind the Raw Tables view.
 *
 * Everything here is pure and unit-tested (lineage-nav.test.ts).
 */

import type { MapLayer } from "./palette";
import type { MapModel, ParsedMap } from "./parse-map";

// ── Deep-link resolution ─────────────────────────────────────────────────────

export type ModelResolution =
  | { kind: "found"; id: string }
  | { kind: "ambiguous"; ids: string[] }
  | { kind: "not-found"; suggestions: string[] };

/**
 * Resolve a URL ref — a bare model name (`rpt_sdr_funnel`, the canonical share
 * form) or a full dbt unique_id (`model.proj.rpt_sdr_funnel`) — against the
 * loaded graph. Names match case-insensitively; a full unique_id wins
 * outright, and its last segment is used as a name fallback so links survive
 * a project rename.
 */
export function resolveModelRef(parsed: ParsedMap, ref: string): ModelResolution {
  const trimmed = ref.trim();
  if (!trimmed) return { kind: "not-found", suggestions: [] };

  // Exact unique_id (case-sensitive first, then insensitive).
  if (parsed.models.has(trimmed)) return { kind: "found", id: trimmed };
  const lower = trimmed.toLowerCase();
  for (const id of parsed.models.keys()) {
    if (id.toLowerCase() === lower) return { kind: "found", id };
  }

  // Name match — for unique_id-shaped refs fall back to the last segment.
  const name = (trimmed.includes(".") ? trimmed.split(".").pop()! : trimmed).toLowerCase();
  const hits: string[] = [];
  for (const m of parsed.models.values()) {
    if (m.name.toLowerCase() === name) hits.push(m.id);
  }
  if (hits.length === 1) return { kind: "found", id: hits[0] };
  if (hits.length > 1) return { kind: "ambiguous", ids: hits.sort() };
  return { kind: "not-found", suggestions: suggestNames(parsed, name) };
}

/**
 * The canonical shareable ref for a node: its bare name when that name is
 * unique in the project, else its full unique_id.
 */
export function canonicalRef(parsed: ParsedMap, id: string): string {
  const model = parsed.models.get(id);
  if (!model) return id;
  const name = model.name.toLowerCase();
  let count = 0;
  for (const m of parsed.models.values()) {
    if (m.name.toLowerCase() === name) count += 1;
    if (count > 1) return id;
  }
  return model.name;
}

/** Build the lineage path for a ref: `/lineage/<ref>` or `/lineage/<ref>/raw`. */
export function lineagePath(ref: string, raw = false): string {
  return `/lineage/${encodeURIComponent(ref)}${raw ? "/raw" : ""}`;
}

// ── Fuzzy suggestions ────────────────────────────────────────────────────────

function editDistance(a: string, b: string, cap: number): number {
  if (Math.abs(a.length - b.length) > cap) return cap + 1;
  const prev = new Array(b.length + 1).fill(0).map((_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    let diag = prev[0];
    prev[0] = i;
    let rowMin = prev[0];
    for (let j = 1; j <= b.length; j++) {
      const tmp = prev[j];
      prev[j] = Math.min(
        prev[j] + 1,
        prev[j - 1] + 1,
        diag + (a[i - 1] === b[j - 1] ? 0 : 1),
      );
      diag = tmp;
      rowMin = Math.min(rowMin, prev[j]);
    }
    if (rowMin > cap) return cap + 1;
  }
  return prev[b.length];
}

/** Up to `limit` closest model names for a typo'd ref (best first). */
export function suggestNames(parsed: ParsedMap, ref: string, limit = 3): string[] {
  const q = ref.toLowerCase();
  if (!q) return [];
  const cap = Math.max(3, Math.floor(q.length / 2));
  const scored: { name: string; score: number }[] = [];
  const seen = new Set<string>();
  for (const m of parsed.models.values()) {
    const name = m.name;
    const key = name.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    let score: number;
    if (key === q) score = 0;
    else if (key.startsWith(q) || q.startsWith(key)) score = 0.5;
    else if (key.includes(q)) score = 1;
    else {
      const d = editDistance(q, key, cap);
      if (d > cap) continue;
      score = 1 + d;
    }
    scored.push({ name, score });
  }
  scored.sort((a, b) => a.score - b.score || a.name.localeCompare(b.name));
  return scored.slice(0, limit).map((s) => s.name);
}

// ── Directional reachability ─────────────────────────────────────────────────

function reach(parsed: ParsedMap, start: string, dir: "parents" | "children"): Set<string> {
  const out = new Set<string>([start]);
  const stack = [start];
  while (stack.length) {
    const cur = stack.pop()!;
    for (const next of parsed.models.get(cur)?.[dir] ?? []) {
      if (!out.has(next)) {
        out.add(next);
        stack.push(next);
      }
    }
  }
  return out;
}

/** All ancestors of `id` (including itself). */
export const upstreamOf = (parsed: ParsedMap, id: string) => reach(parsed, id, "parents");
/** All descendants of `id` (including itself). */
export const downstreamOf = (parsed: ParsedMap, id: string) => reach(parsed, id, "children");

/** Every node on any path from `sourceId` down to `focusId` (inclusive). */
export function pathBetween(parsed: ParsedMap, sourceId: string, focusId: string): Set<string> {
  const down = downstreamOf(parsed, sourceId);
  const up = upstreamOf(parsed, focusId);
  const out = new Set<string>();
  for (const id of down) if (up.has(id)) out.add(id);
  out.add(sourceId);
  out.add(focusId);
  return out;
}

// ── Staged columns (focus mode) ──────────────────────────────────────────────

/** One vocabulary everywhere — the technical stage names. */
export const STAGE_LABELS = ["Sources", "Staging", "Intermediate", "Dims / Facts", "Marts"] as const;

const LAYER_STAGE: Partial<Record<MapLayer, number>> = {
  source: 0,
  staging: 1,
  intermediate: 2,
  dimension: 3,
  fact: 3,
  mart: 4,
};

export interface StagedColumns {
  /** Present stages in pipeline order, each with its member ids. */
  stages: { label: string; ids: string[] }[];
  /** id -> index into `stages`. */
  columnOf: Map<string, number>;
}

/**
 * Assign every node in a lineage cone to a labeled stage column. Layered
 * projects map directly; `other` nodes are placed one stage past their
 * deepest in-cone parent (graph depth), so unconventional projects still get
 * a sensible left-to-right story.
 */
export function stageColumns(parsed: ParsedMap, coneIds: Set<string>): StagedColumns {
  const stageOf = new Map<string, number>();
  const pending: string[] = [];
  for (const id of coneIds) {
    const layer = parsed.models.get(id)?.layer;
    const stage = layer !== undefined ? LAYER_STAGE[layer] : undefined;
    if (stage !== undefined) stageOf.set(id, stage);
    else pending.push(id);
  }
  // Graph-depth placement for `other`, iterated to a fixed point (cones are small).
  let changed = true;
  let guard = 0;
  while (changed && guard++ < 50) {
    changed = false;
    for (const id of pending) {
      const parents = (parsed.models.get(id)?.parents ?? []).filter((p) => coneIds.has(p));
      const known = parents.map((p) => stageOf.get(p)).filter((s): s is number => s !== undefined);
      const next = known.length ? Math.min(4, Math.max(...known) + 1) : 1;
      if (stageOf.get(id) !== next) {
        stageOf.set(id, next);
        changed = true;
      }
    }
  }

  const present = [...new Set([...stageOf.values()])].sort((a, b) => a - b);
  const columnIndex = new Map(present.map((stage, i) => [stage, i]));
  const stages = present.map((stage) => ({ label: STAGE_LABELS[stage], ids: [] as string[] }));
  const columnOf = new Map<string, number>();
  for (const [id, stage] of stageOf) {
    const col = columnIndex.get(stage)!;
    stages[col].ids.push(id);
    columnOf.set(id, col);
  }
  for (const s of stages) {
    s.ids.sort((a, b) => parsed.models.get(a)!.name.localeCompare(parsed.models.get(b)!.name));
  }
  return { stages, columnOf };
}

// ── Raw Tables rollup ────────────────────────────────────────────────────────

export interface RawSourceRow {
  id: string;
  name: string;
  /** `database.schema.name` (whatever parts exist), for the mono identifier line. */
  relation: string;
  /** Distinct dependency paths from this table to the focused model. */
  pathCount: number;
  /** False for lineage roots that are plain models — "not declared as a source". */
  declared: boolean;
}

export interface RawSourcesResult {
  rows: RawSourceRow[];
  /** Direct parents of the focus — shown when no raw sources exist. */
  buildsOn: MapModel[];
}

/**
 * Deduplicated raw tables feeding `focusId`: every source-layer ancestor,
 * plus non-source lineage roots (hygiene: tables read without a `source()`
 * declaration). Path counts are exact distinct-path counts over the DAG.
 */
export function rawSourcesFor(parsed: ParsedMap, focusId: string): RawSourcesResult {
  const up = upstreamOf(parsed, focusId);

  // Distinct paths v -> focus, memoized over the upstream DAG.
  const memo = new Map<string, number>([[focusId, 1]]);
  const countPaths = (id: string): number => {
    const hit = memo.get(id);
    if (hit !== undefined) return hit;
    memo.set(id, 0); // cycle guard (dbt DAGs are acyclic; belt and braces)
    let total = 0;
    for (const child of parsed.models.get(id)?.children ?? []) {
      if (up.has(child)) total += countPaths(child);
    }
    memo.set(id, total);
    return total;
  };

  const rows: RawSourceRow[] = [];
  for (const id of up) {
    if (id === focusId) continue;
    const m = parsed.models.get(id);
    if (!m) continue;
    const isSource = m.layer === "source";
    const isRoot = m.parents.length === 0;
    if (!isSource && !isRoot) continue;
    rows.push({
      id,
      name: m.name,
      relation: [m.database, m.schema, m.name].filter(Boolean).join("."),
      pathCount: countPaths(id),
      declared: isSource,
    });
  }
  rows.sort(
    (a, b) =>
      Number(b.declared) - Number(a.declared) ||
      b.pathCount - a.pathCount ||
      a.name.localeCompare(b.name),
  );

  const buildsOn = (parsed.models.get(focusId)?.parents ?? [])
    .map((id) => parsed.models.get(id))
    .filter((m): m is MapModel => Boolean(m));
  return { rows, buildsOn };
}
