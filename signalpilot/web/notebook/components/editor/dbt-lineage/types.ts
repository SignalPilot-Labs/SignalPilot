export interface DbtManifestNode {
  unique_id: string;
  name: string;
  resource_type: "model" | "seed" | "test" | "source" | "snapshot";
  description: string;
  path: string;
  original_file_path: string;
  database: string;
  schema: string;
  alias: string;
  tags: string[];
  columns: Record<string, DbtColumn>;
  config: {
    materialized?: string;
    tags?: string[];
    schema?: string;
    [key: string]: unknown;
  };
  depends_on: {
    macros: string[];
    nodes: string[];
  };
  compiled_path?: string;
  raw_code?: string;
  relation_name?: string;
  package_name?: string;
  fqn: string[];
  refs: Array<{ name: string; package?: string; version?: string }>;
  primary_key?: string[];
}

export interface DbtColumn {
  name: string;
  description: string;
  meta: Record<string, unknown>;
  data_type: string | null;
  constraints: unknown[];
  quote: boolean | null;
  tags: string[];
}

export interface DbtTestNode {
  unique_id: string;
  name: string;
  resource_type: "test";
  test_metadata?: {
    name: string;
    kwargs: Record<string, unknown>;
  };
  depends_on: {
    macros: string[];
    nodes: string[];
  };
  attached_node?: string;
  tags: string[];
  config: Record<string, unknown>;
}

export interface DbtManifest {
  metadata: {
    dbt_schema_version: string;
    dbt_version: string;
    generated_at: string;
    project_name: string;
  };
  nodes: Record<string, DbtManifestNode | DbtTestNode>;
  sources: Record<string, DbtManifestNode>;
  parent_map: Record<string, string[]>;
  child_map: Record<string, string[]>;
}

export interface DbtRunResult {
  unique_id: string;
  status: "success" | "error" | "skipped" | "pass" | "fail" | "warn";
  execution_time: number;
  message: string;
  timing: Array<{ name: string; started_at: string; completed_at: string }>;
}

export interface DbtRunResults {
  metadata: {
    dbt_version: string;
    generated_at: string;
  };
  results: DbtRunResult[];
  elapsed_time: number;
}

export type DbtModelLayer =
  | "seed"
  | "staging"
  | "intermediate"
  | "dimension"
  | "fact"
  | "mart"
  | "other";

export interface DbtLineageNode {
  id: string;
  name: string;
  resourceType: string;
  layer: DbtModelLayer;
  materialization: string;
  description: string;
  schema: string;
  database: string;
  columns: DbtColumn[];
  columnCount: number;
  testCount: number;
  tests: DbtTestInfo[];
  tags: string[];
  rawCode?: string;
  parents: string[];
  children: string[];
  fqn: string[];
  path: string;
  runStatus?: "success" | "error" | "skipped" | "pass" | "fail" | "warn";
  runTime?: number;
}

export interface DbtTestInfo {
  name: string;
  type: string;
  column?: string;
  status?: string;
}

export interface DbtLineageEdge {
  id: string;
  source: string;
  target: string;
}

export interface DbtLineageData {
  nodes: Map<string, DbtLineageNode>;
  edges: DbtLineageEdge[];
  layers: Map<DbtModelLayer, string[]>;
  projectName: string;
  dbtVersion: string;
}

export type LayoutDirection = "TB" | "LR";

export interface LineageFilterState {
  layers: Set<DbtModelLayer>;
  showTests: boolean;
  searchQuery: string;
}
