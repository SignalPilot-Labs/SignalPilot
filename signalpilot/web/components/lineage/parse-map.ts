/**
 * Distilled dbt map (gateway /dbt-map graph payload) -> typed structures for
 * the lineage page: model nodes, edges, layer classification, schema grouping,
 * per-model test rollups, and upstream/downstream reachability.
 */

import type { MapLayer } from "./palette";

// Shape served by the gateway (a strict subset of a dbt manifest).
interface RawNode {
  name?: string;
  resource_type?: string;
  path?: string | null;
  original_file_path?: string | null;
  fqn?: string[];
  schema?: string | null;
  database?: string | null;
  description?: string | null;
  tags?: string[];
  config?: { materialized?: string | null };
  columns?: Record<string, { name?: string; description?: string; data_type?: string | null }>;
  test_metadata?: { name?: string; kwargs?: Record<string, unknown> };
}

export interface RawMapGraph {
  metadata?: { dbt_version?: string; project_name?: string; generated_at?: string };
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
  columns: { name: string; description: string; dataType?: string }[];
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
}

const NON_GRAPH_TYPES = new Set(["test", "unit_test", "operation", "macro", "exposure", "metric"]);

function classifyLayer(id: string, node: RawNode): MapLayer {
  if (node.resource_type === "source" || node.resource_type === "seed" || id.startsWith("source.")) {
    return "source";
  }
  const name = (node.name ?? "").toLowerCase();
  const path = (node.path ?? node.original_file_path ?? "").toLowerCase().replaceAll("\\", "/");
  const fqn = (node.fqn ?? []).map((s) => s.toLowerCase());
  const inPath = (seg: string) => path.includes(`/${seg}/`) || path.startsWith(`${seg}/`) || fqn.includes(seg);

  if (name.startsWith("stg_") || name.startsWith("base_") || inPath("staging")) return "staging";
  if (name.startsWith("int_") || inPath("intermediate")) return "intermediate";
  if (name.startsWith("dim_") || inPath("dimensions")) return "dimension";
  if (name.startsWith("fct_") || name.startsWith("fact_") || inPath("facts")) return "fact";
  if (
    name.startsWith("mart_") || name.startsWith("agg_") || name.startsWith("rpt_") ||
    inPath("marts") || inPath("reporting")
  ) {
    return "mart";
  }
  return "other";
}

export function parseMap(raw: RawMapGraph): ParsedMap {
  const parentMap = raw.parent_map ?? {};
  const childMap = raw.child_map ?? {};
  const all: Record<string, RawNode> = { ...(raw.nodes ?? {}), ...(raw.sources ?? {}) };

  // Per-model tests come from test nodes hanging off child_map.
  const testsFor = (id: string): MapTest[] => {
    const tests: MapTest[] = [];
    for (const childId of childMap[id] ?? []) {
      if (!childId.startsWith("test.") && !childId.startsWith("unit_test.")) continue;
      const t = all[childId];
      if (!t) continue;
      tests.push({
        name: t.name ?? childId,
        type: t.test_metadata?.name ?? "generic",
        column:
          (t.test_metadata?.kwargs?.column_name as string | undefined) ??
          (t.test_metadata?.kwargs?.field as string | undefined),
      });
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
      columns: Object.values(node.columns ?? {}).map((c) => ({
        name: c.name ?? "",
        description: c.description ?? "",
        dataType: c.data_type ?? undefined,
      })),
      tests: testsFor(id),
      parents: graphRel(parentMap[id]),
      children: graphRel(childMap[id]),
    });
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
  for (const model of models.values()) layerCounts[model.layer] += 1;

  return {
    models,
    edges,
    schemas: new Map([...schemas.entries()].sort(([a], [b]) => a.localeCompare(b))),
    layerCounts,
    projectName: raw.metadata?.project_name ?? "dbt project",
    dbtVersion: raw.metadata?.dbt_version ?? "",
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
