import { atom, useAtom, useAtomValue, useSetAtom } from "jotai";
import { atomWithStorage } from "jotai/utils";
import { useCallback } from "react";
import { toast } from "@/components/ui/use-toast";
import { spApiUrl } from "@/core/network/api";
import { getApiHeaders } from "@/core/network/api-headers";
import type {
  DbtCommandRequest,
  DbtCommandResponse,
  DbtCommandStatus,
  DbtLogEntry,
  DbtProjectInfo,
} from "./types";


async function dbtFetch<T>(
  endpoint: string,
  body: Record<string, unknown>,
): Promise<T> {
  const response = await fetch(spApiUrl(`/dbt${endpoint}`), {
    method: "POST",
    headers: await getApiHeaders(),
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const text = await response.text().catch(() => response.statusText);
    throw new Error(`dbt API error (${response.status}): ${text}`);
  }
  return response.json() as Promise<T>;
}

// Persisted project directory - survives page reloads
export const dbtProjectDirAtom = atomWithStorage<string | null>(
  "sp:dbt-project-dir",
  null,
);

// Atoms
export const dbtStatusAtom = atom<DbtCommandStatus>("idle");
export const dbtLogsAtom = atom<DbtLogEntry[]>([]);
export const dbtProjectInfoAtom = atom<DbtProjectInfo | null>(null);
export const dbtPanelOpenAtom = atom(false);

// Derived
export const dbtLogCountAtom = atom((get) => get(dbtLogsAtom).length);
export const isRunningDbtAtom = atom((get) => get(dbtStatusAtom) === "running");

let logIdCounter = 0;

export function useDbtActions() {
  const [status, setStatus] = useAtom(dbtStatusAtom);
  const setLogs = useSetAtom(dbtLogsAtom);
  const setProjectInfo = useSetAtom(dbtProjectInfoAtom);
  const setPanelOpen = useSetAtom(dbtPanelOpenAtom);
  const [projectDir, setProjectDir] = useAtom(dbtProjectDirAtom);

  const runCommand = useCallback(
    async (command: string, args?: string[]) => {
      if (status === "running") {
        toast({
          title: "dbt",
          description: "A dbt command is already running",
          variant: "danger",
        });
        return null;
      }

      setStatus("running");

      const request: DbtCommandRequest = {
        command,
        args,
        projectDir: projectDir,
      };

      try {
        const result = await dbtFetch<DbtCommandResponse>(
          "/command",
          request as unknown as Record<string, unknown>,
        );

        const entry: DbtLogEntry = {
          id: `dbt-${++logIdCounter}`,
          timestamp: Date.now(),
          command: `dbt ${command}${args?.length ? ` ${args.join(" ")}` : ""}`,
          success: result.success,
          exitCode: result.exitCode,
          stdout: result.stdout,
          stderr: result.stderr,
          durationMs: result.durationMs,
        };

        setLogs((prev) => [entry, ...prev]);
        setStatus(result.success ? "success" : "error");

        toast({
          title: result.success ? "dbt" : "dbt error",
          description: result.success
            ? `dbt ${command} completed in ${(result.durationMs / 1000).toFixed(1)}s`
            : `dbt ${command} failed (exit code ${result.exitCode})`,
          variant: result.success ? "default" : "danger",
        });

        return result;
      } catch (error) {
        setStatus("error");
        const message =
          error instanceof Error ? error.message : "Unknown error";
        toast({
          title: "dbt error",
          description: message,
          variant: "danger",
        });
        return null;
      }
    },
    [status, setStatus, setLogs, projectDir],
  );

  const refreshProjectInfo = useCallback(
    async (dir?: string) => {
      try {
        const info = await dbtFetch<DbtProjectInfo>("/project_info", {
          projectDir: dir || projectDir,
        });
        setProjectInfo(info);
        if (info.found && info.projectDir) {
          setProjectDir(info.projectDir);
        }
        return info;
      } catch {
        return null;
      }
    },
    [setProjectInfo, projectDir, setProjectDir],
  );

  const clearLogs = useCallback(() => {
    setLogs([]);
  }, [setLogs]);

  return {
    runCommand,
    refreshProjectInfo,
    clearLogs,
    setPanelOpen,
    projectDir,
    setProjectDir,
  };
}

export function useDbtStatus() {
  return useAtomValue(dbtStatusAtom);
}

export function useDbtLogs() {
  return useAtomValue(dbtLogsAtom);
}

export function useDbtProjectInfo() {
  return useAtomValue(dbtProjectInfoAtom);
}

export function useIsDbtPanelOpen() {
  return useAtomValue(dbtPanelOpenAtom);
}

// ── Project discovery & management (used by home page) ──────────

export async function discoverDbtProjects(
  rootDir?: string,
): Promise<import("./types").DbtDiscoverResponse> {
  return dbtFetch("/discover_projects", { rootDir });
}

export async function scaffoldDbtProject(
  request: import("./types").DbtScaffoldRequest,
): Promise<import("./types").DbtScaffoldResponse> {
  return dbtFetch("/scaffold_project", request as unknown as Record<string, unknown>);
}

export async function cloneDbtProject(
  request: import("./types").DbtCloneRequest,
): Promise<import("./types").DbtCloneResponse> {
  return dbtFetch("/clone_project", request as unknown as Record<string, unknown>);
}

// ── Model-scoped commands ───────────────────────────────────────

export function getModelNameFromPath(filePath: string): string | null {
  if (!filePath.endsWith(".sql")) {return null;}
  const parts = filePath.replace(/\\/g, "/").split("/");
  const filename = parts[parts.length - 1];
  return filename.replace(".sql", "");
}

export function isDbtModelFile(filePath: string): boolean {
  const normalized = filePath.replace(/\\/g, "/");
  return normalized.endsWith(".sql") && normalized.includes("/models/");
}

export async function compileModel(
  modelName: string,
  projectDir?: string | null,
): Promise<import("./types").DbtCompileModelResponse> {
  return dbtFetch("/compile_model", { modelName, projectDir });
}

export async function previewModel(
  modelName: string,
  projectDir?: string | null,
  limit = 500,
): Promise<import("./types").DbtPreviewModelResponse> {
  return dbtFetch("/preview_model", { modelName, projectDir, limit });
}

// State atoms for the console panel
export const dbtConsoleTabAtom = atom<import("./types").DbtConsoleTab>("logs");
export const dbtCompiledSqlAtom = atom<string>("");
export const dbtPreviewResultsAtom = atom<import("./types").DbtPreviewModelResponse | null>(null);
export const dbtConsoleOpenAtom = atom(false);
