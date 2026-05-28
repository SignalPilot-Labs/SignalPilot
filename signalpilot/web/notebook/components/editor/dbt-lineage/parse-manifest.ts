import type {
  DbtLineageData,
  DbtLineageEdge,
  DbtLineageNode,
  DbtManifest,
  DbtManifestNode,
  DbtModelLayer,
  DbtRunResults,
  DbtTestInfo,
  DbtTestNode,
} from "./types";

function classifyLayer(node: DbtManifestNode): DbtModelLayer {
  if (node.resource_type === "seed") {
    return "seed";
  }
  if (node.resource_type === "source") {
    return "seed";
  }

  const name = node.name.toLowerCase();
  const path = (node.path || "").toLowerCase();
  const fqn = node.fqn?.map((s) => s.toLowerCase()) ?? [];

  if (
    name.startsWith("stg_") ||
    path.includes("/staging/") ||
    fqn.includes("staging")
  ) {
    return "staging";
  }
  if (
    name.startsWith("int_") ||
    path.includes("/intermediate/") ||
    fqn.includes("intermediate")
  ) {
    return "intermediate";
  }
  if (
    name.startsWith("dim_") ||
    path.includes("/dimensions/") ||
    fqn.includes("dimensions")
  ) {
    return "dimension";
  }
  if (
    name.startsWith("fct_") ||
    name.startsWith("fact_") ||
    path.includes("/facts/") ||
    fqn.includes("facts")
  ) {
    return "fact";
  }
  if (
    name.startsWith("mart_") ||
    name.startsWith("agg_") ||
    name.startsWith("rpt_") ||
    path.includes("/marts/") ||
    fqn.includes("marts")
  ) {
    return "mart";
  }

  return "other";
}

function extractTests(
  nodeId: string,
  childMap: Record<string, string[]>,
  allNodes: Record<string, DbtManifestNode | DbtTestNode>,
  runResultMap: Map<string, { status: string }>,
): DbtTestInfo[] {
  const children = childMap[nodeId] ?? [];
  const tests: DbtTestInfo[] = [];

  for (const childId of children) {
    if (!childId.startsWith("test.")) {
      continue;
    }
    const testNode = allNodes[childId] as DbtTestNode | undefined;
    if (!testNode) {
      continue;
    }

    const meta = testNode.test_metadata;
    const testType = meta?.name ?? "generic";
    const column =
      (meta?.kwargs?.column_name as string) ??
      (meta?.kwargs?.field as string) ??
      undefined;

    const runResult = runResultMap.get(childId);

    tests.push({
      name: testNode.name,
      type: testType,
      column: column,
      status: runResult?.status,
    });
  }

  return tests;
}

export function parseManifest(
  manifest: DbtManifest,
  runResults?: DbtRunResults | null,
): DbtLineageData {
  const nodes = new Map<string, DbtLineageNode>();
  const edges: DbtLineageEdge[] = [];
  const layers = new Map<DbtModelLayer, string[]>();

  const runResultMap = new Map<string, { status: string }>();
  if (runResults?.results) {
    for (const r of runResults.results) {
      runResultMap.set(r.unique_id, {
        status: r.status,
      });
    }
  }

  const parentMap = manifest.parent_map ?? {};
  const childMap = manifest.child_map ?? {};

  for (const [id, node] of Object.entries(manifest.nodes)) {
    if (node.resource_type === "test") {
      continue;
    }

    const modelNode = node as DbtManifestNode;
    const layer = classifyLayer(modelNode);
    const columns = Object.values(modelNode.columns ?? {});
    const tests = extractTests(id, childMap, manifest.nodes, runResultMap);
    const runResult = runResultMap.get(id);

    const parents = (parentMap[id] ?? []).filter((p) => !p.startsWith("test."));
    const children = (childMap[id] ?? []).filter(
      (c) => !c.startsWith("test."),
    );

    const lineageNode: DbtLineageNode = {
      id,
      name: modelNode.name,
      resourceType: modelNode.resource_type,
      layer,
      materialization: modelNode.config?.materialized ?? "unknown",
      description: modelNode.description || "",
      schema: modelNode.schema || "",
      database: modelNode.database || "",
      columns,
      columnCount: columns.length,
      testCount: tests.length,
      tests,
      tags: modelNode.tags ?? [],
      rawCode: modelNode.raw_code,
      parents,
      children,
      fqn: modelNode.fqn ?? [],
      path: modelNode.path || modelNode.original_file_path || "",
      runStatus: runResult?.status as DbtLineageNode["runStatus"],
      runTime: runResults?.results.find((r) => r.unique_id === id)
        ?.execution_time,
    };

    nodes.set(id, lineageNode);

    const existing = layers.get(layer) ?? [];
    existing.push(id);
    layers.set(layer, existing);
  }

  for (const [id, source] of Object.entries(manifest.sources ?? {})) {
    const columns = Object.values(source.columns ?? {});
    const parents = (parentMap[id] ?? []).filter((p) => !p.startsWith("test."));
    const children = (childMap[id] ?? []).filter(
      (c) => !c.startsWith("test."),
    );

    nodes.set(id, {
      id,
      name: source.name,
      resourceType: "source",
      layer: "seed",
      materialization: "source",
      description: source.description || "",
      schema: source.schema || "",
      database: source.database || "",
      columns,
      columnCount: columns.length,
      testCount: 0,
      tests: [],
      tags: source.tags ?? [],
      parents,
      children,
      fqn: source.fqn ?? [],
      path: source.path || source.original_file_path || "",
    });

    const existing = layers.get("seed") ?? [];
    existing.push(id);
    layers.set("seed", existing);
  }

  const edgeSet = new Set<string>();
  for (const [childId, parentIds] of Object.entries(parentMap)) {
    if (!nodes.has(childId)) {
      continue;
    }
    for (const parentId of parentIds) {
      if (!nodes.has(parentId)) {
        continue;
      }
      const edgeId = `${parentId}->${childId}`;
      if (!edgeSet.has(edgeId)) {
        edgeSet.add(edgeId);
        edges.push({ id: edgeId, source: parentId, target: childId });
      }
    }
  }

  return {
    nodes,
    edges,
    layers,
    projectName: manifest.metadata?.project_name ?? "dbt project",
    dbtVersion: manifest.metadata?.dbt_version ?? "",
  };
}
