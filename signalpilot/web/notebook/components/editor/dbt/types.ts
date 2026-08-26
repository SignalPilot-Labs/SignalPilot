export interface DbtCommandRequest {
  command: string;
  args?: string[];
  projectDir?: string | null;
  profilesDir?: string | null;
  target?: string | null;
}

export interface DbtCommandResponse {
  success: boolean;
  command: string;
  exitCode: number;
  stdout: string;
  stderr: string;
  durationMs: number;
  projectDir: string | null;
}

export interface DbtProjectInfo {
  success: boolean;
  found: boolean;
  projectDir: string | null;
  projectName: string | null;
  profile: string | null;
  modelPaths: string[];
  seedPaths: string[];
  testPaths: string[];
  macroPaths: string[];
  snapshotPaths: string[];
  hasManifest: boolean;
  hasProfiles: boolean;
  dbtVersion: string | null;
  dbtInstalled: boolean;
}

export interface DbtModel {
  unique_id: string;
  name: string;
  path: string;
  materialized: string;
  schema: string;
  database: string;
  description: string;
  depends_on: string[];
  tags: string[];
}

export interface DbtModelsResponse {
  success: boolean;
  models: DbtModel[];
  projectDir: string | null;
}

export interface DbtLogEntry {
  id: string;
  timestamp: number;
  command: string;
  success: boolean;
  exitCode: number;
  stdout: string;
  stderr: string;
  durationMs: number;
}

export type DbtCommandStatus = "idle" | "running" | "success" | "error";

// Project discovery & management

export interface DbtProjectSummary {
  projectDir: string;
  projectName: string | null;
  profile: string | null;
  lastModified: number | null;
}

export interface DbtDiscoverResponse {
  success: boolean;
  projects: DbtProjectSummary[];
  rootDir: string | null;
}

export interface DbtScaffoldRequest {
  projectName: string;
  parentDir?: string | null;
  adapter?: string;
}

export interface DbtScaffoldResponse {
  success: boolean;
  projectDir: string | null;
  error: string | null;
  filesCreated: string[];
}

export interface DbtCloneRequest {
  gitUrl: string;
  targetDir?: string | null;
  branch?: string | null;
}

export interface DbtCloneResponse {
  success: boolean;
  projectDir: string | null;
  projectName: string | null;
  error: string | null;
}

// Model-scoped commands

export interface DbtCompileModelResponse {
  success: boolean;
  compiledSql: string;
  error: string | null;
}

export interface DbtPreviewColumn {
  name: string;
  type: string;
}

export interface DbtPreviewModelResponse {
  success: boolean;
  columns: DbtPreviewColumn[];
  rows: string[][];
  rowCount: number;
  error: string | null;
}

export type DbtConsoleTab = "results" | "compiled" | "logs";
