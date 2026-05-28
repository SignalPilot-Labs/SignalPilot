import { atom, useAtomValue, useSetAtom } from "jotai";

export interface ActiveFile {
  path: string;
  type: "raw" | "notebook";
}

const RAW_EXTENSIONS = new Set([
  ".sql", ".yml", ".yaml", ".json", ".toml", ".txt", ".csv", ".md", ".qmd",
]);

const NOTEBOOK_EXTENSIONS = new Set([".py"]);

export function classifyFile(path: string): "raw" | "notebook" | "unknown" {
  const ext = path.slice(path.lastIndexOf(".")).toLowerCase();
  if (RAW_EXTENSIONS.has(ext)) {return "raw";}
  if (NOTEBOOK_EXTENSIONS.has(ext)) {return "notebook";}
  return "unknown";
}

export const activeFileAtom = atom<ActiveFile | null>(null);

export function useActiveFile() {
  return useAtomValue(activeFileAtom);
}

export function useSetActiveFile() {
  return useSetAtom(activeFileAtom);
}
