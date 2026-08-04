import { atom, useAtomValue, useSetAtom } from "jotai";
import {
  getGatewayBranchId,
  getGatewayProjectId,
  spApiUrl,
} from "@/core/network/api";
import { getApiHeaders } from "@/core/network/api-headers";

export type FileKind = "raw" | "notebook";
export type FileKindHint = "raw" | "ambiguous" | "unknown";

export interface ActiveFile {
  path: string;
  type: FileKind;
}

const RAW_EXTENSIONS = new Set([
  ".sql", ".yml", ".yaml", ".json", ".toml", ".txt", ".csv",
]);

const AMBIGUOUS_EXTENSIONS = new Set([".py", ".md", ".qmd"]);
const fileKindCache = new Map<string, Promise<FileKind>>();

export function classifyFile(path: string): FileKindHint {
  const dotIndex = path.lastIndexOf(".");
  const ext = dotIndex === -1 ? "" : path.slice(dotIndex).toLowerCase();
  if (RAW_EXTENSIONS.has(ext)) {return "raw";}
  if (AMBIGUOUS_EXTENSIONS.has(ext)) {return "ambiguous";}
  return "unknown";
}

function cacheKey(path: string): string {
  return [
    getGatewayProjectId() ?? "",
    getGatewayBranchId() ?? "",
    path.replace(/\\/g, "/"),
  ].join(":");
}

export async function resolveFileKind(path: string): Promise<FileKind> {
  if (classifyFile(path) === "raw") {
    return "raw";
  }

  const key = cacheKey(path);
  const cached = fileKindCache.get(key);
  if (cached) {
    return cached;
  }

  const pending = (async () => {
    const headers = await getApiHeaders();
    const response = await fetch(
      spApiUrl(`/notebook/static?file=${encodeURIComponent(path)}`),
      { headers },
    );
    if (!response.ok) {
      throw new Error(`Could not classify file (${response.status})`);
    }
    const payload = (await response.json()) as { rawFallback?: boolean };
    return payload.rawFallback ? "raw" : "notebook";
  })();
  fileKindCache.set(key, pending);

  try {
    return await pending;
  } catch (error) {
    fileKindCache.delete(key);
    throw error;
  }
}

export function invalidateFileKind(path: string): void {
  const normalizedPath = path.replace(/\\/g, "/");
  for (const key of fileKindCache.keys()) {
    if (key.endsWith(`:${normalizedPath}`)) {
      fileKindCache.delete(key);
    }
  }
}

export const activeFileAtom = atom<ActiveFile | null>(null);

export function useActiveFile() {
  return useAtomValue(activeFileAtom);
}

export function useSetActiveFile() {
  return useSetAtom(activeFileAtom);
}
