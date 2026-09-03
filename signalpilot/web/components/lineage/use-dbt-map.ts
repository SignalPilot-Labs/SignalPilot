"use client";

/**
 * Data plane for the dbt map page: project bootstrap (remembered in
 * localStorage, overridable by a `?project=` deep link), map fetch + parse,
 * live polling for recompiles on watched branches, and manual compile.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { useToast } from "~/components/ui/toast";
import { compileDbtMap, getDbtMap, getWorkspaceProjects } from "~/lib/api";
import type { DbtMapInfo, WorkspaceProjectInfo } from "~/lib/types";
import { parseMap, type ParsedMap, type RawMapGraph } from "./parse-map";

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
  parsed: ParsedMap | null;
  compiling: boolean;
  compileNow: () => Promise<void>;
}

export function useDbtMap(initialProjectId?: string | null): DbtMapState {
  const { toast } = useToast();
  const [projects, setProjects] = useState<WorkspaceProjectInfo[]>([]);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [mapInfo, setMapInfo] = useState<DbtMapInfo | null>(null);
  const [mapStatus, setMapStatus] = useState<MapStatus>("loading");
  const [parsed, setParsed] = useState<ParsedMap | null>(null);
  const [compiling, setCompiling] = useState(false);
  const lastUpdatedRef = useRef<number>(0);

  const project = projects.find((p) => p.id === projectId) ?? null;
  const watched: string[] =
    (project?.settings?.watched_branches as string[] | undefined) ??
    (project ? [project.default_branch || "main"] : []);

  // Projects bootstrap; a ?project= deep link overrides the remembered choice.
  useEffect(() => {
    getWorkspaceProjects("active")
      .then(({ projects: list }) => {
        setProjects(list);
        const remembered =
          list.find((p) => p.id === initialProjectId) ??
          list.find((p) => p.id === localStorage.getItem(PROJECT_KEY)) ??
          list[0];
        if (remembered) setProjectId(remembered.id);
        else setMapStatus("no-projects");
      })
      .catch(() => setMapStatus("error"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadMap = useCallback(async (pid: string, { quiet = false } = {}) => {
    if (!quiet) setMapStatus("loading");
    try {
      const res = await getDbtMap(pid);
      setMapInfo(res.map);
      setMapStatus(res.status);
      if (res.status === "success" && res.graph) {
        setParsed(parseMap(res.graph as unknown as RawMapGraph));
        lastUpdatedRef.current = res.map?.updated_at ?? 0;
      } else if (!quiet) {
        setParsed(null);
      }
    } catch {
      setMapStatus("error");
    }
  }, []);

  useEffect(() => {
    if (!projectId) return;
    localStorage.setItem(PROJECT_KEY, projectId);
    setParsed(null);
    void loadMap(projectId);
  }, [projectId, loadMap]);

  // Live auto-update: a push/PR to a watched branch recompiles the map on the
  // gateway; when a newer revision lands, hot-swap the graph.
  useEffect(() => {
    if (!projectId) return;
    const interval = setInterval(async () => {
      try {
        const res = await getDbtMap(projectId, undefined, false);
        if (res.status === "running" || res.status === "queued") {
          setMapStatus(res.status);
          setMapInfo(res.map);
          return;
        }
        if (
          res.status === "success" &&
          res.map &&
          res.map.updated_at > lastUpdatedRef.current
        ) {
          await loadMap(projectId, { quiet: true });
          toast(
            `dbt map updated${res.map.trigger ? ` · trigger: ${res.map.trigger}` : ""}`,
            "success",
          );
        }
      } catch {
        // transient poll failure — next tick retries
      }
    }, POLL_MS);
    return () => clearInterval(interval);
  }, [projectId, loadMap, toast]);

  const compileNow = useCallback(async () => {
    if (!projectId || compiling) return;
    setCompiling(true);
    try {
      await compileDbtMap(projectId);
      setMapStatus("running");
      toast("compile started on a sandbox", "success");
    } catch (e) {
      toast(String(e), "error");
    } finally {
      setCompiling(false);
    }
  }, [projectId, compiling, toast]);

  return {
    projects,
    projectId,
    setProjectId,
    project,
    watched,
    mapInfo,
    mapStatus,
    parsed,
    compiling,
    compileNow,
  };
}
