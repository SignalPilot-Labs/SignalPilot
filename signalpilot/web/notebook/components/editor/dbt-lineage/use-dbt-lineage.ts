import { atom, useAtom, useAtomValue } from "jotai";
import { useCallback, useEffect } from "react";
import { dbtProjectDirAtom } from "@/components/editor/dbt/use-dbt";
import { toast } from "@/components/ui/use-toast";
import { getApiHeaders } from "@/core/network/api-headers";
import { getRuntimeManager } from "@/core/runtime/config";
import type {
  DbtLineageData,
  DbtLineageNode,
  DbtManifest,
  DbtRunResults,
  LayoutDirection,
  LineageFilterState,
  DbtModelLayer,
} from "./types";
import { parseManifest } from "./parse-manifest";

function getApiBase(): string {
  const rm = getRuntimeManager();
  const base = rm.httpURL.toString().replace(/\/$/, "");
  return `${base}/api/dbt`;
}

async function fetchArtifact<T>(
  artifact: string,
  projectDir?: string | null,
): Promise<T | null> {
  const response = await fetch(`${getApiBase()}/artifact`, {
    method: "POST",
    headers: await getApiHeaders(),
    body: JSON.stringify({ artifact, projectDir }),
  });
  if (!response.ok) {
    return null;
  }
  const result = await response.json() as { success?: boolean; data?: T };
  if (!result.success || !result.data) {
    return null;
  }
  return result.data;
}

// State atoms
export const lineageDataAtom = atom<DbtLineageData | null>(null);
export const lineageLoadingAtom = atom(false);
export const lineageErrorAtom = atom<string | null>(null);
export const selectedNodeAtom = atom<DbtLineageNode | null>(null);
export const layoutDirectionAtom = atom<LayoutDirection>("LR");

const ALL_LAYERS: DbtModelLayer[] = [
  "seed",
  "staging",
  "intermediate",
  "dimension",
  "fact",
  "mart",
  "other",
];

export const lineageFilterAtom = atom<LineageFilterState>({
  layers: new Set<DbtModelLayer>(ALL_LAYERS),
  showTests: false,
  searchQuery: "",
});

export function useDbtLineage() {
  const projectDir = useAtomValue(dbtProjectDirAtom);
  const [data, setData] = useAtom(lineageDataAtom);
  const [loading, setLoading] = useAtom(lineageLoadingAtom);
  const [error, setError] = useAtom(lineageErrorAtom);

  const loadLineage = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const [manifest, runResults] = await Promise.all([
        fetchArtifact<DbtManifest>("manifest", projectDir),
        fetchArtifact<DbtRunResults>("run_results", projectDir),
      ]);

      if (!manifest) {
        setError(
          "No manifest found. Run 'dbt parse' or 'dbt compile' first.",
        );
        setData(null);
        return;
      }

      const parsed = parseManifest(manifest, runResults);
      setData(parsed);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to load manifest";
      setError(msg);
      toast({
        title: "Lineage error",
        description: msg,
        variant: "danger",
      });
    } finally {
      setLoading(false);
    }
  }, [projectDir, setData, setLoading, setError]);

  useEffect(() => {
    if (!data && !loading && !error) {
      loadLineage();
    }
  }, [data, loading, error, loadLineage]);

  return { data, loading, error, reload: loadLineage };
}

export function useSelectedNode() {
  return useAtom(selectedNodeAtom);
}

export function useLayoutDirection() {
  return useAtom(layoutDirectionAtom);
}

export function useLineageFilter() {
  const [filter, setFilter] = useAtom(lineageFilterAtom);

  const toggleLayer = useCallback(
    (layer: DbtModelLayer) => {
      setFilter((prev) => {
        const next = new Set(prev.layers);
        if (next.has(layer)) {
          next.delete(layer);
        } else {
          next.add(layer);
        }
        return { ...prev, layers: next };
      });
    },
    [setFilter],
  );

  const setSearch = useCallback(
    (query: string) => {
      setFilter((prev) => ({ ...prev, searchQuery: query }));
    },
    [setFilter],
  );

  const toggleTests = useCallback(() => {
    setFilter((prev) => ({ ...prev, showTests: !prev.showTests }));
  }, [setFilter]);

  return { filter, toggleLayer, setSearch, toggleTests };
}
