"use client";

/**
 * Data plane for the dbt map page, on top of the module-level lineage cache.
 *
 * Load order for a deep link (`?project=` + model ref): the cone request and
 * the skeleton request start together, immediately. The projects list loads
 * in parallel and only feeds the header picker (or picks the project when
 * the URL names none). The cone paints the focused view first; the skeleton
 * replaces it silently when it lands. Repeat visits are served from the
 * cache with no request at all.
 *
 * Polling (20 s, `include_graph=false`) watches `updated_at`; a newer map
 * invalidates the cache entry and reloads the skeleton (and the current
 * cone) in the background.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { useToast } from "~/components/ui/toast";
import { compileDbtMap, getDbtMap, getWorkspaceProjects } from "~/lib/api";
import {
  lineageCache,
  type ConeLoad,
  type LineageCache,
  type ModelSql,
  type SkeletonLoad,
} from "~/lib/lineage-cache";
import type { DbtMapInfo, WorkspaceProjectInfo } from "~/lib/types";
import type { MapColumn, ParsedMap } from "./parse-map";

const POLL_MS = 20_000;
const PROJECT_KEY = "sp:lineage-project";

export type MapStatus =
  | "loading"
  | "none"
  | "queued"
  | "running"
  | "success"
  | "failed"
  | "error"
  | "no-projects";

export interface DbtMapState {
  projects: WorkspaceProjectInfo[];
  projectId: string | null;
  setProjectId: (id: string) => void;
  project: WorkspaceProjectInfo | null;
  watched: string[];
  mapInfo: DbtMapInfo | null;
  mapStatus: MapStatus;
  /** The skeleton when loaded, else the cone sub-graph, else null. */
  parsed: ParsedMap | null;
  /** True while only the cone is on screen (full graph still loading). */
  partial: boolean;
  compiling: boolean;
  compileNow: () => Promise<void>;
}

export interface UseDbtMapOptions {
  /** Persist the chosen project as the remembered lineage project. */
  remember?: boolean;
  /** Report load status changes (embedded hosts render their own error UI). */
  onStatusChange?: (status: MapStatus) => void;
  /** Injectable for tests; defaults to the shared module cache. */
  cache?: LineageCache;
}

export function useDbtMap(
  routeProjectId: string | null,
  focusRef: string | null,
  { remember = true, onStatusChange, cache = lineageCache }: UseDbtMapOptions = {},
): DbtMapState {
  const { toast } = useToast();
  const [projects, setProjects] = useState<WorkspaceProjectInfo[]>([]);
  const [noProjects, setNoProjects] = useState(false);
  const [projectId, setProjectId] = useState<string | null>(routeProjectId);
  const [skeleton, setSkeleton] = useState<SkeletonLoad | null>(() =>
    routeProjectId ? cache.peekSkeleton(routeProjectId) : null,
  );
  const [cone, setCone] = useState<ConeLoad | null>(null);
  const [failed, setFailed] = useState(false);
  const [compiling, setCompiling] = useState(false);
  const focusRefRef = useRef(focusRef);
  focusRefRef.current = focusRef;

  // A ?project= change after mount switches projects like the picker does.
  useEffect(() => {
    if (routeProjectId) setProjectId(routeProjectId);
  }, [routeProjectId]);

  // Projects list: header picker, and the project choice when the URL has none.
  useEffect(() => {
    let cancelled = false;
    getWorkspaceProjects("active")
      .then(({ projects: list }) => {
        if (cancelled) return;
        setProjects(list);
        setProjectId((current) => {
          if (current) return current;
          const pick =
            list.find((p) => p.id === localStorage.getItem(PROJECT_KEY)) ?? list[0];
          if (!pick) setNoProjects(true);
          return pick?.id ?? null;
        });
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Skeleton + cone for the active project, both from the cache.
  useEffect(() => {
    if (!projectId) return;
    if (remember) localStorage.setItem(PROJECT_KEY, projectId);
    let cancelled = false;
    setFailed(false);
    const cached = cache.peekSkeleton(projectId);
    setSkeleton(cached);
    setCone(null);
    cache
      .loadSkeleton(projectId)
      .then((s) => {
        if (!cancelled) setSkeleton(s);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, remember, cache]);

  // Cone for the focused model while the skeleton is still loading. Keyed on
  // the ref itself: on a cold first render the URL ref can arrive after the
  // project effect ran, and the cone must still fire then.
  useEffect(() => {
    if (!projectId || !focusRef) return;
    if (cache.peekSkeleton(projectId)) return;
    let cancelled = false;
    void cache.loadCone(projectId, focusRef).then((c) => {
      if (!cancelled && c) setCone(c);
    });
    return () => {
      cancelled = true;
    };
  }, [projectId, focusRef, cache]);

  // Live auto-update: a push/PR to a watched branch recompiles the map on the
  // gateway; when a newer revision lands, hot-swap the graph.
  useEffect(() => {
    if (!projectId) return;
    const interval = setInterval(async () => {
      try {
        const res = await getDbtMap(projectId, undefined, false);
        if (res.status === "running" || res.status === "queued") {
          setSkeleton((cur) => ({ status: res.status, mapInfo: res.map, parsed: cur?.parsed ?? null }));
          return;
        }
        if (res.status !== "success" || !res.map) return;
        if (!cache.invalidate(projectId, null, res.map.updated_at)) return;
        const ref = focusRefRef.current;
        if (ref) void cache.loadCone(projectId, ref);
        const next = await cache.loadSkeleton(projectId);
        setSkeleton(next);
        toast(
          `dbt map updated${res.map.trigger ? ` · trigger: ${res.map.trigger}` : ""}`,
          "success",
        );
      } catch {
        // transient poll failure; the next tick retries
      }
    }, POLL_MS);
    return () => clearInterval(interval);
  }, [projectId, cache, toast]);

  const compileNow = useCallback(async () => {
    if (!projectId || compiling) return;
    setCompiling(true);
    try {
      await compileDbtMap(projectId);
      setSkeleton((cur) => ({ status: "running", mapInfo: cur?.mapInfo ?? null, parsed: cur?.parsed ?? null }));
      toast("compile started on a sandbox", "success");
    } catch (e) {
      toast(String(e), "error");
    } finally {
      setCompiling(false);
    }
  }, [projectId, compiling, toast]);

  const source = skeleton ?? cone;
  const mapStatus: MapStatus = failed
    ? "error"
    : noProjects && !projectId
      ? "no-projects"
      : source
        ? source.status
        : "loading";

  const statusCb = useRef(onStatusChange);
  statusCb.current = onStatusChange;
  useEffect(() => {
    statusCb.current?.(mapStatus);
  }, [mapStatus]);

  const project = projects.find((p) => p.id === projectId) ?? null;
  const watched: string[] =
    (project?.settings?.watched_branches as string[] | undefined) ??
    (project ? [project.default_branch || "main"] : []);

  return {
    projects,
    projectId,
    setProjectId,
    project,
    watched,
    mapInfo: source?.mapInfo ?? null,
    mapStatus,
    parsed: skeleton?.parsed ?? cone?.parsed ?? null,
    partial: !skeleton?.parsed && Boolean(cone?.parsed),
    compiling,
    compileNow,
  };
}

/** Columns for one model: from the cache when present, else one request. */
export function useModelColumns(
  projectId: string | null,
  modelId: string | null,
  cache: LineageCache = lineageCache,
): { columns: MapColumn[] | null; loading: boolean } {
  const [state, setState] = useState<{ id: string | null; columns: MapColumn[] | null }>({
    id: null,
    columns: null,
  });
  const peek = projectId && modelId ? cache.peekColumns(projectId, modelId) : null;
  useEffect(() => {
    if (!projectId || !modelId || cache.peekColumns(projectId, modelId)) return;
    let cancelled = false;
    cache
      .loadColumns(projectId, [modelId])
      .then((res) => {
        if (!cancelled) setState({ id: modelId, columns: res[modelId] ?? [] });
      })
      .catch(() => {
        if (!cancelled) setState({ id: modelId, columns: [] });
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, modelId, cache]);
  const columns = peek ?? (state.id === modelId ? state.columns : null);
  return { columns, loading: columns === null };
}

export type ModelSqlState =
  | { state: "idle" }
  | { state: "loading" }
  | { state: "ready"; sql: ModelSql }
  | { state: "unavailable" }
  | { state: "error" };

/** SQL for one model, lazily through the cache. `enabled` defers the fetch. */
export function useModelSql(
  projectId: string | null,
  modelId: string | null,
  enabled = true,
  cache: LineageCache = lineageCache,
): ModelSqlState {
  const [state, setState] = useState<{ id: string | null; value: ModelSqlState }>({
    id: null,
    value: { state: "idle" },
  });
  const peek = projectId && modelId ? cache.peekSql(projectId, modelId) : undefined;
  useEffect(() => {
    if (!enabled || !projectId || !modelId) return;
    if (cache.peekSql(projectId, modelId) !== undefined) return;
    let cancelled = false;
    setState({ id: modelId, value: { state: "loading" } });
    cache
      .loadSql(projectId, modelId)
      .then((sql) => {
        if (cancelled) return;
        setState({ id: modelId, value: sql ? { state: "ready", sql } : { state: "unavailable" } });
      })
      .catch(() => {
        if (!cancelled) setState({ id: modelId, value: { state: "error" } });
      });
    return () => {
      cancelled = true;
    };
  }, [enabled, projectId, modelId, cache]);
  if (peek !== undefined) return peek ? { state: "ready", sql: peek } : { state: "unavailable" };
  if (!enabled) return { state: "idle" };
  return state.id === modelId ? state.value : { state: "loading" };
}
