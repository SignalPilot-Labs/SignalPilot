import { atom, useAtom, useAtomValue } from "jotai";
import { useCallback, useEffect } from "react";
import { dbtProjectDirAtom } from "@/components/editor/dbt/use-dbt";
import { toast } from "@/components/ui/use-toast";
import { getApiHeaders } from "@/core/network/api-headers";
import {
  gatewayBranchIdAtom,
  gatewayProjectIdAtom,
} from "@/core/network/gateway-state";
import { getRuntimeManager } from "@/core/runtime/config";
import { compileDbtMap, getDbtMap } from "~/lib/api";
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

// Stored dbt map: the gateway-compiled graph is a manifest-shaped subset, so
// the existing parser consumes it directly.
async function fetchStoredGraph(
  projectId: string,
  branch: string | null,
): Promise<DbtManifest | null> {
  try {
    const res = await getDbtMap(projectId, branch ?? undefined);
    if (res.status === "success" && res.graph) {
      return res.graph as unknown as DbtManifest;
    }
  } catch {
    // Gateway map unavailable (older gateway, gated tier) — fall back to live.
  }
  return null;
}

// State atoms
export const lineageDataAtom = atom<DbtLineageData | null>(null);
export const lineageLoadingAtom = atom(false);
export const lineageErrorAtom = atom<string | null>(null);
export const lineageCompilingAtom = atom(false);
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
  const projectId = useAtomValue(gatewayProjectIdAtom);
  const branchId = useAtomValue(gatewayBranchIdAtom);
  const [data, setData] = useAtom(lineageDataAtom);
  const [loading, setLoading] = useAtom(lineageLoadingAtom);
  const [error, setError] = useAtom(lineageErrorAtom);
  const [compiling, setCompiling] = useAtom(lineageCompilingAtom);

  const loadLineage = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      // Preferred source: the gateway-stored dbt map. It survives sandbox
      // restarts and revision bumps, and needs no manual `dbt parse`.
      if (projectId) {
        const stored = await fetchStoredGraph(projectId, branchId);
        if (stored) {
          setData(parseManifest(stored, null));
          return;
        }
      }

      // Fallback: live artifacts from the notebook runtime (covers unsaved
      // local state and projects with no compiled map yet).
      const [manifest, runResults] = await Promise.all([
        fetchArtifact<DbtManifest>("manifest", projectDir),
        fetchArtifact<DbtRunResults>("run_results", projectDir),
      ]);

      if (!manifest) {
        setError(
          "No dbt map compiled yet. Use 'compile map' (or run 'dbt parse') first.",
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
  }, [projectDir, projectId, branchId, setData, setLoading, setError]);

  const recompile = useCallback(async () => {
    if (!projectId || compiling) {
      return;
    }
    setCompiling(true);
    try {
      await compileDbtMap(projectId, branchId ?? undefined);
      toast({
        title: "dbt map",
        description: "Compile started on a sandbox...",
      });
      // Poll until the job settles, then refresh the graph.
      for (let i = 0; i < 60; i++) {
        await new Promise((resolve) => setTimeout(resolve, 5000));
        const res = await getDbtMap(projectId, branchId ?? undefined, false);
        if (res.status === "success") {
          await loadLineage();
          toast({ title: "dbt map", description: "Lineage map updated" });
          return;
        }
        if (res.status === "failed") {
          const msg = res.map?.error || "Compile failed";
          setError(msg);
          toast({ title: "dbt map", description: msg, variant: "danger" });
          return;
        }
      }
      toast({
        title: "dbt map",
        description: "Compile is taking a while — check back shortly.",
      });
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to start compile";
      toast({ title: "dbt map", description: msg, variant: "danger" });
    } finally {
      setCompiling(false);
    }
  }, [projectId, branchId, compiling, setCompiling, setError, loadLineage]);

  useEffect(() => {
    if (!data && !loading && !error) {
      loadLineage();
    }
  }, [data, loading, error, loadLineage]);

  return { data, loading, error, reload: loadLineage, recompile, compiling };
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
