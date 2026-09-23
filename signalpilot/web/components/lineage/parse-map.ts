/**
 * Distilled dbt map (gateway /dbt-map graph payload) -> typed structures for
 * the lineage page: model nodes, edges, layer classification, schema grouping,
 * per-model test rollups, and upstream/downstream reachability.
 *
 * Accepts every graph variant the gateway serves: `full` (test nodes present,
 * columns inline as a record), `skeleton` (no test nodes, no columns, each
 * node carries `column_count` and inline `tests`), and `cone` (skeleton
 * nodes limited to one model's lineage, the focused model with columns).
 */

import type { MapLayer } from "./palette";

// Shape served by the gateway (a strict subset of a dbt manifest).
export interface RawNode {
  name?: string;
  resource_type?: string;
  path?: string | null;
  original_file_path?: string | null;
  fqn?: string[];
  schema?: string | null;
  database?: string | null;
  description?: string | null;
  tags?: string[];
  /** The project's own `meta.layer`, when it declares one. */
  layer?: string | null;
  config?: { materialized?: string | null };
  columns?: RawColumn[] | Record<string, RawColumn>;
  /** Skeleton nodes: column total without the column payload. */
  column_count?: number;
  /** Skeleton nodes: the model's tests inline (no test nodes in the graph). */
  tests?: { name?: string; test_metadata?: RawNode["test_metadata"] }[];
  test_metadata?: { name?: string; kwargs?: Record<string, unknown> };
}

export interface RawColumn {
  name?: string;
  description?: string | null;
  data_type?: string | null;
}

export interface MapColumn {
  name: string;
  description: string;
  dataType?: string;
}

export interface RawMapGraph {
  metadata?: {
    dbt_version?: string;
    project_name?: string;
    generated_at?: string;
    variant?: "full" | "skeleton" | "cone";
  };
  nodes?: Record<string, RawNode>;
  sources?: Record<string, RawNode>;
  parent_map?: Record<string, string[]>;
  child_map?: Record<string, string[]>;
}

export interface MapTest {
  name: string;
  type: string;
  column?: string;
}

export interface MapModel {
  id: string;
  name: string;
  resourceType: string;
  layer: MapLayer;
  materialized: string;
  schema: string;
  database: string;
  description: string;
  path: string;
  tags: string[];
  /** Empty until loaded for skeleton nodes; see `columnsLoaded`. */
  columns: MapColumn[];
  /** Column total, known even when `columns` is not loaded yet. */
  columnCount: number;
  /** False for skeleton nodes whose columns must be fetched on demand. */
  columnsLoaded: boolean;
  tests: MapTest[];
  parents: string[];
  children: string[];
}

export interface MapEdge {
  id: string;
  source: string;
  target: string;
}

export interface ParsedMap {
  models: Map<string, MapModel>;
  edges: MapEdge[];
  /** database.schema -> ordered model ids (marts first inside a schema). */
  schemas: Map<string, string[]>;
  layerCounts: Record<MapLayer, number>;
  projectName: string;
  dbtVersion: string;
  /** Which gateway variant produced this graph. */
  variant: "full" | "skeleton" | "cone";
}

const NON_GRAPH_TYPES = new Set(["test", "unit_test", "operation", "macro", "exposure", "metric"]);

/**
 * A model's layer, from the strongest signal in the compiled manifest down.
 * dbt has no layer field (`resource_type` is just "model"), so:
 *
 * 1. An explicit declaration: `meta.layer` (served as `layer`) or a tag
 *    naming a layer.
 * 2. `dim_` / `fct_` names. Dimensions and facts usually share the marts
 *    schema and dbt has no fact/dim flag, so the name is the only signal.
 * 3. The compiled `schema`: the custom schema each folder sets in
 *    dbt_project.yml. dbt prefixes it with the target schema
 *    (`dbt_prod_staging`), so its last `_` token counts too.
 * 4. The model's folders (`fqn` and path).
 * 5. The remaining name prefixes (`stg_`, `int_`, `mart_`, ...).
 *
 * Models nothing places are classified by graph position in `parseMap`.
 */
function classifyLayer(id: string, node: RawNode): MapLayer {
  if (node.resource_type === "source" || node.resource_type === "seed" || id.startsWith("source.")) {
    return "source";
  }
  const declared = [node.layer, ...(node.tags ?? [])]
    .map((value) => declaredLayer(value))
    .find((layer) => layer !== null);
  if (declared) return declared;

  const name = (node.name ?? "").toLowerCase();
  const byName = (rules: [MapLayer, string[]][]) =>
    rules.find(([, prefixes]) => prefixes.some((prefix) => name.startsWith(prefix)))?.[0];
  const dimOrFact = byName(DIM_FACT_PREFIXES);
  if (dimOrFact) return dimOrFact;

  const schema = (node.schema ?? "").toLowerCase();
  const fromSchema = layerFromWord(schema) ?? layerFromWord(schema.split("_").pop());
  if (fromSchema) return fromSchema;

  const path = (node.path ?? node.original_file_path ?? "").toLowerCase().replaceAll("\\", "/");
  const folders = [...path.split("/").slice(0, -1), ...(node.fqn ?? []).slice(1, -1).map((s) => s.toLowerCase())];
  const fromFolder = folders.map((folder) => layerFromWord(folder)).find((layer) => layer !== null);
  if (fromFolder) return fromFolder;

  return byName(LAYER_PREFIXES) ?? "other";
}

/** Words that name a layer, as a schema, folder, tag or `meta.layer`. */
const LAYER_WORDS: Record<string, MapLayer> = {
  staging: "staging", stg: "staging", base: "staging",
  intermediate: "intermediate", int: "intermediate", core: "intermediate", prep: "intermediate",
  dimension: "dimension", dimensions: "dimension", dim: "dimension", dims: "dimension",
  fact: "fact", facts: "fact", fct: "fact",
  mart: "mart", marts: "mart", reporting: "mart", report: "mart", reports: "mart",
};

function layerFromWord(word: string | null | undefined): MapLayer | null {
  if (!word) return null;
  return LAYER_WORDS[word.trim().toLowerCase()] ?? null;
}

/** Tags and `meta.layer` count only when they spell a layer out in full:
 * a `core` or `base` tag often means "important", not a layer. */
const DECLARED_WORDS = new Set([
  "staging", "intermediate", "dimension", "dimensions", "fact", "facts", "mart", "marts",
]);

function declaredLayer(word: string | null | undefined): MapLayer | null {
  const normalized = word?.trim().toLowerCase() ?? "";
  return DECLARED_WORDS.has(normalized) ? layerFromWord(normalized) : null;
}

const DIM_FACT_PREFIXES: [MapLayer, string[]][] = [
  ["dimension", ["dim_"]],
  ["fact", ["fct_", "fact_"]],
];

const LAYER_PREFIXES: [MapLayer, string[]][] = [
  ["staging", ["stg_", "base_"]],
  ["intermediate", ["int_", "core_", "prep_"]],
  ["mart", ["mart_", "agg_", "rpt_", "report_"]],
];

/** Normalize a column payload (record in `full`, array in `skeleton`/`cone`). */
export function parseColumns(raw: RawNode["columns"] | null | undefined): MapColumn[] {
  if (!raw) return [];
  const list = Array.isArray(raw) ? raw : Object.values(raw);
  return list.map((c) => ({
    name: c.name ?? "",
    description: c.description ?? "",
    dataType: c.data_type ?? undefined,
  }));
}

function testEntry(name: string, meta: RawNode["test_metadata"]): MapTest {
  return {
    name,
    type: meta?.name ?? "generic",
    column:
      (meta?.kwargs?.column_name as string | undefined) ??
      (meta?.kwargs?.field as string | undefined),
  };
}

export function parseMap(raw: RawMapGraph): ParsedMap {
  const parentMap = raw.parent_map ?? {};
  const childMap = raw.child_map ?? {};
  const all: Record<string, RawNode> = { ...(raw.nodes ?? {}), ...(raw.sources ?? {}) };

  // Per-model tests: inline on skeleton nodes, else test nodes off child_map.
  const testsFor = (id: string, node: RawNode): MapTest[] => {
    if (node.tests) return node.tests.map((t) => testEntry(t.name ?? "test", t.test_metadata));
    const tests: MapTest[] = [];
    for (const childId of childMap[id] ?? []) {
      if (!childId.startsWith("test.") && !childId.startsWith("unit_test.")) continue;
      const t = all[childId];
      if (t) tests.push(testEntry(t.name ?? childId, t.test_metadata));
    }
    return tests;
  };

  const isGraphNode = (id: string, n: RawNode) =>
    !NON_GRAPH_TYPES.has(n.resource_type ?? "") &&
    !id.startsWith("test.") &&
    !id.startsWith("unit_test.");

  const models = new Map<string, MapModel>();
  for (const [id, node] of Object.entries(all)) {
    if (!isGraphNode(id, node)) continue;
    const layer = classifyLayer(id, node);
    const graphRel = (ids: string[] | undefined) =>
      (ids ?? []).filter((p) => all[p] && isGraphNode(p, all[p]));
    const columns = parseColumns(node.columns);
    const columnsLoaded = node.columns !== undefined && node.columns !== null;
    models.set(id, {
      id,
      name: node.name ?? id.split(".").pop() ?? id,
      resourceType: node.resource_type ?? "model",
      layer,
      materialized:
        layer === "source" ? "source" : node.config?.materialized ?? "view",
      schema: node.schema ?? "",
      database: node.database ?? "",
      description: node.description ?? "",
      path: node.path ?? node.original_file_path ?? "",
      tags: node.tags ?? [],
      columns,
      columnCount: columnsLoaded ? columns.length : node.column_count ?? 0,
      columnsLoaded,
      tests: testsFor(id, node),
      parents: graphRel(parentMap[id]),
      children: graphRel(childMap[id]),
    });
  }

  // Models no name or folder rule placed are classified by position: one that
  // feeds other models is intermediate work, one that feeds nothing is an
  // endpoint and reads as a mart. Only a model with no graph neighbours at
  // all stays "other".
  for (const model of models.values()) {
    if (model.layer !== "other") continue;
    if (model.children.length > 0) model.layer = "intermediate";
    else if (model.parents.length > 0) model.layer = "mart";
  }

  const edges: MapEdge[] = [];
  const seen = new Set<string>();
  for (const model of models.values()) {
    for (const parent of model.parents) {
      const key = `${parent}->${model.id}`;
      if (!seen.has(key) && models.has(parent)) {
        seen.add(key);
        edges.push({ id: key, source: parent, target: model.id });
      }
    }
  }

  const schemas = new Map<string, string[]>();
  for (const model of models.values()) {
    const key = [model.database, model.schema].filter(Boolean).join(".") || "(no schema)";
    if (!schemas.has(key)) schemas.set(key, []);
    schemas.get(key)!.push(model.id);
  }
  for (const ids of schemas.values()) {
    ids.sort((a, b) => models.get(a)!.name.localeCompare(models.get(b)!.name));
  }

  const layerCounts = {
    source: 0, staging: 0, intermediate: 0, dimension: 0, fact: 0, mart: 0, other: 0,
  } as Record<MapLayer, number>;
  // Legend counts what the canvas draws: dbt sources are never drawn.
  for (const model of models.values()) {
    if (model.resourceType !== "source") layerCounts[model.layer] += 1;
  }

  return {
    models,
    edges,
    schemas: new Map([...schemas.entries()].sort(([a], [b]) => a.localeCompare(b))),
    layerCounts,
    projectName: raw.metadata?.project_name ?? "dbt project",
    dbtVersion: raw.metadata?.dbt_version ?? "",
    variant: raw.metadata?.variant ?? "full",
  };
}

/** Every id reachable upstream + downstream of `id` (including itself). */
export function lineageCone(map: ParsedMap, id: string): Set<string> {
  const cone = new Set<string>([id]);
  const walk = (start: string, dir: "parents" | "children") => {
    const stack = [start];
    while (stack.length) {
      const current = stack.pop()!;
      for (const next of map.models.get(current)?.[dir] ?? []) {
        if (!cone.has(next)) {
          cone.add(next);
          stack.push(next);
        }
      }
    }
  };
  walk(id, "parents");
  walk(id, "children");
  return cone;
}
