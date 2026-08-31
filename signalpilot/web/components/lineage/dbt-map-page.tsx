"use client";

/**
 * The dbt map — SignalPilot's lineage home. dbt-style DAG (left-to-right,
 * accent-edged cards, source pills) expanded with: a schema explorer window,
 * hover lineage-cone focus, double-click isolation, an inspector drawer, and
 * live auto-update when a push/PR to a watched branch recompiles the map.
 */

import {
  ChevronDown,
  ChevronRight,
  Crosshair,
  Hammer,
  Loader2,
  RefreshCw,
  Search,
  X,
} from "lucide-react";
import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import ReactFlow, {
  Background,
  BackgroundVariant,
  Controls,
  type Edge,
  MarkerType,
  MiniMap,
  type Node,
  ReactFlowProvider,
  useReactFlow,
} from "reactflow";
import "reactflow/dist/style.css";
import { graphlib, layout as dagreLayout } from "@dagrejs/dagre";

import { useToast } from "~/components/ui/toast";
import {
  compileDbtMap,
  getDbtMap,
  getWorkspaceProjects,
} from "~/lib/api";
import type { DbtMapInfo, WorkspaceProjectInfo } from "~/lib/types";
import { LAYER_COLOR, LAYER_LABEL, LAYER_ORDER, type MapLayer, matGlyph } from "./palette";
import { MapNode, NODE_H, NODE_W, type MapNodeData, mapNodeTypes } from "./map-node";
import {
  lineageCone,
  type MapModel,
  parseMap,
  type ParsedMap,
  type RawMapGraph,
} from "./parse-map";

const POLL_MS = 20_000;

function timeAgo(epoch: number): string {
  const s = Math.max(0, Math.floor(Date.now() / 1000 - epoch));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

// ── Layout ───────────────────────────────────────────────────────────────────

function layoutNodes(models: MapModel[], edges: { source: string; target: string }[]) {
  const g = new graphlib.Graph().setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "LR", nodesep: 28, ranksep: 110, ranker: "network-simplex", marginx: 48, marginy: 48 });
  for (const m of models) g.setNode(m.id, { width: NODE_W, height: NODE_H });
  for (const e of edges) if (g.hasNode(e.source) && g.hasNode(e.target)) g.setEdge(e.source, e.target);
  dagreLayout(g);
  const pos = new Map<string, { x: number; y: number }>();
  for (const m of models) {
    const p = g.node(m.id);
    pos.set(m.id, { x: p.x - NODE_W / 2, y: p.y - NODE_H / 2 });
  }
  return pos;
}

// ── Canvas ───────────────────────────────────────────────────────────────────

function MapCanvas({
  parsed,
  visibleLayers,
  query,
  selectedId,
  focusId,
  onSelect,
  onFocus,
}: {
  parsed: ParsedMap;
  visibleLayers: Set<MapLayer>;
  query: string;
  selectedId: string | null;
  focusId: string | null;
  onSelect: (id: string | null) => void;
  onFocus: (id: string | null) => void;
}) {
  const api = useReactFlow();
  const [hoverId, setHoverId] = useState<string | null>(null);
  const [initTick, setInitTick] = useState(0);

  const focusCone = useMemo(
    () => (focusId ? lineageCone(parsed, focusId) : null),
    [parsed, focusId],
  );

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    const ids = new Set<string>();
    for (const m of parsed.models.values()) {
      if (!visibleLayers.has(m.layer)) continue;
      if (q && !m.name.toLowerCase().includes(q) && !m.schema.toLowerCase().includes(q)) continue;
      if (focusCone && !focusCone.has(m.id)) continue;
      ids.add(m.id);
    }
    return ids;
  }, [parsed, visibleLayers, query, focusCone]);

  const positions = useMemo(() => {
    const models = [...visible].map((id) => parsed.models.get(id)!);
    const edges = parsed.edges.filter((e) => visible.has(e.source) && visible.has(e.target));
    return layoutNodes(models, edges);
  }, [parsed, visible]);

  // The active lineage path: selection wins over hover.
  const pathCone = useMemo(() => {
    const anchor = selectedId ?? hoverId;
    if (!anchor || !visible.has(anchor)) return null;
    return lineageCone(parsed, anchor);
  }, [parsed, selectedId, hoverId, visible]);

  const rfNodes: Node<MapNodeData>[] = useMemo(
    () =>
      [...visible].map((id) => {
        const model = parsed.models.get(id)!;
        return {
          id,
          type: "dbtMap",
          position: positions.get(id) ?? { x: 0, y: 0 },
          width: NODE_W,
          height: NODE_H,
          data: {
            model,
            onPath: pathCone ? pathCone.has(id) : null,
            selected: id === selectedId,
          },
        };
      }),
    [parsed, visible, positions, pathCone, selectedId],
  );

  const rfEdges: Edge[] = useMemo(
    () =>
      parsed.edges
        .filter((e) => visible.has(e.source) && visible.has(e.target))
        .map((e) => {
          const onPath = pathCone ? pathCone.has(e.source) && pathCone.has(e.target) : null;
          const color = LAYER_COLOR[parsed.models.get(e.source)!.layer];
          return {
            id: e.id,
            source: e.source,
            target: e.target,
            type: "bezier",
            animated: onPath === true,
            markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color },
            style: {
              stroke: color,
              strokeWidth: onPath ? 2 : 1.25,
              opacity: onPath === null ? 0.3 : onPath ? 0.95 : 0.04,
              transition: "opacity 150ms",
            },
          };
        }),
    [parsed, visible, pathCone],
  );

  // Initial camera: a fit-all of a big DAG (hundreds of sources in one rank)
  // is unreadable dust. Open on the marts/facts — the layer people came for —
  // at a readable zoom; the Controls fit button still frames everything.
  useEffect(() => {
    const t = setTimeout(() => {
      const ids = [...visible];
      const anchorIds =
        ids.length > 80
          ? ids.filter((id) => {
              const layer = parsed.models.get(id)!.layer;
              return layer === "mart" || layer === "fact";
            })
          : [];
      const targets = anchorIds.length >= 2 ? anchorIds : ids;
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      for (const id of targets) {
        const p = positions.get(id);
        if (!p) continue;
        minX = Math.min(minX, p.x);
        minY = Math.min(minY, p.y);
        maxX = Math.max(maxX, p.x + NODE_W);
        maxY = Math.max(maxY, p.y + NODE_H);
      }
      if (Number.isFinite(minX)) {
        api.fitBounds(
          { x: minX, y: minY, width: maxX - minX, height: maxY - minY },
          { padding: 0.15, duration: 400 },
        );
      } else {
        api.fitView({ padding: 0.1, duration: 400 });
      }
    }, 120);
    return () => clearTimeout(t);
  }, [api, parsed, positions, visible, focusId, initTick]);

  // External selection (schema panel / inspector nav) -> center the node.
  useEffect(() => {
    if (!selectedId) return;
    const p = positions.get(selectedId);
    if (p) api.setCenter(p.x + NODE_W / 2, p.y + NODE_H / 2, { zoom: 1, duration: 500 });
  }, [selectedId, positions, api]);

  return (
    <ReactFlow
      nodes={rfNodes}
      edges={rfEdges}
      nodeTypes={mapNodeTypes}
      onNodeClick={(_, n) => onSelect(n.id === selectedId ? null : n.id)}
      onNodeDoubleClick={(_, n) => onFocus(n.id)}
      onNodeMouseEnter={(_, n) => setHoverId(n.id)}
      onNodeMouseLeave={() => setHoverId(null)}
      onPaneClick={() => onSelect(null)}
      onInit={() => setInitTick((t) => t + 1)}
      minZoom={0.05}
      maxZoom={2.5}
      zoomOnDoubleClick={false}
      nodesConnectable={false}
      nodesDraggable
      proOptions={{ hideAttribution: true }}
    >
      <Background color="rgba(255,255,255,0.055)" variant={BackgroundVariant.Dots} gap={22} size={1} />
      <Controls
        position="bottom-right"
        showInteractive={false}
        className="!border-[var(--color-border)] !bg-[var(--color-bg-card)] !shadow-none [&>button]:!border-[var(--color-border)] [&>button]:!bg-[var(--color-bg-card)] [&>button]:!text-[var(--color-text-muted)] [&>button:hover]:!bg-[var(--color-bg-hover)]"
      />
      <MiniMap
        position="top-right"
        pannable
        zoomable
        className="!h-28 !w-44 !border !border-[var(--color-border)] !bg-[var(--color-bg)]"
        maskColor="rgba(14,14,15,0.75)"
        nodeColor={(n) => LAYER_COLOR[(n.data as MapNodeData).model.layer]}
        nodeStrokeWidth={0}
      />
    </ReactFlow>
  );
}

// ── Schema explorer window ───────────────────────────────────────────────────

function SchemaWindow({
  parsed,
  query,
  selectedId,
  onSelect,
}: {
  parsed: ParsedMap;
  query: string;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const q = query.trim().toLowerCase();

  return (
    <div className="flex h-full w-60 shrink-0 flex-col border-r border-[var(--color-border)] bg-[var(--color-bg-card)]/60">
      <div className="border-b border-[var(--color-border)] px-3 py-2 text-[10px] uppercase tracking-[0.1em] text-[var(--color-text-dim)]">
        schemas
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto py-1">
        {[...parsed.schemas.entries()].map(([schema, ids]) => {
          const rows = q
            ? ids.filter((id) => parsed.models.get(id)!.name.toLowerCase().includes(q))
            : ids;
          if (q && rows.length === 0) return null;
          const isCollapsed = collapsed.has(schema) && !q;
          return (
            <div key={schema}>
              <button
                type="button"
                onClick={() =>
                  setCollapsed((prev) => {
                    const next = new Set(prev);
                    if (next.has(schema)) next.delete(schema);
                    else next.add(schema);
                    return next;
                  })
                }
                className="flex w-full items-center gap-1 px-2 py-1.5 text-left text-[11px] text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
              >
                {isCollapsed ? <ChevronRight className="h-3 w-3 shrink-0" /> : <ChevronDown className="h-3 w-3 shrink-0" />}
                <span className="truncate font-mono">{schema}</span>
                <span className="ml-auto text-[9px] text-[var(--color-text-dim)]">{rows.length}</span>
              </button>
              {!isCollapsed &&
                rows.map((id) => {
                  const m = parsed.models.get(id)!;
                  const active = id === selectedId;
                  return (
                    <button
                      key={id}
                      type="button"
                      onClick={() => onSelect(id)}
                      className={`flex w-full items-center gap-1.5 py-[3px] pl-7 pr-2 text-left font-mono text-[10.5px] leading-tight transition-colors ${
                        active
                          ? "bg-[var(--color-bg-hover)] text-[var(--color-text)]"
                          : "text-[var(--color-text-muted)] hover:bg-[var(--color-bg-hover)]/60 hover:text-[var(--color-text)]"
                      }`}
                    >
                      <span
                        className="h-1.5 w-1.5 shrink-0 rounded-[2px]"
                        style={{ background: LAYER_COLOR[m.layer] }}
                        aria-hidden="true"
                      />
                      <span className="w-3 shrink-0 text-center text-[9px]" style={{ color: LAYER_COLOR[m.layer] }} aria-hidden="true">
                        {matGlyph(m.materialized, m.layer)}
                      </span>
                      <span className="truncate">{m.name}</span>
                    </button>
                  );
                })}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Inspector drawer ─────────────────────────────────────────────────────────

function Inspector({
  parsed,
  model,
  onClose,
  onNavigate,
}: {
  parsed: ParsedMap;
  model: MapModel;
  onClose: () => void;
  onNavigate: (id: string) => void;
}) {
  const color = LAYER_COLOR[model.layer];
  const relList = (ids: string[], label: string) =>
    ids.length > 0 && (
      <div>
        <div className="mb-1 text-[9px] uppercase tracking-[0.1em] text-[var(--color-text-dim)]">
          {label} ({ids.length})
        </div>
        <div className="flex flex-col gap-px">
          {ids.map((id) => {
            const rel = parsed.models.get(id);
            if (!rel) return null;
            return (
              <button
                key={id}
                type="button"
                onClick={() => onNavigate(id)}
                className="flex items-center gap-1.5 rounded px-1.5 py-1 text-left font-mono text-[10.5px] text-[var(--color-text-muted)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
              >
                <span className="h-1.5 w-1.5 shrink-0 rounded-[2px]" style={{ background: LAYER_COLOR[rel.layer] }} aria-hidden="true" />
                <span className="truncate">{rel.name}</span>
              </button>
            );
          })}
        </div>
      </div>
    );

  return (
    <div className="flex h-full w-72 shrink-0 flex-col border-l border-[var(--color-border)] bg-[var(--color-bg-card)]/80 backdrop-blur">
      <div className="flex items-start justify-between gap-2 border-b border-[var(--color-border)] p-3">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5">
            <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded text-[10px]" style={{ color, background: `${color}1f` }} aria-hidden="true">
              {matGlyph(model.materialized, model.layer)}
            </span>
            <span className="truncate font-mono text-xs font-bold text-[var(--color-text)]">{model.name}</span>
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[9px] leading-none">
            <span className="rounded-[4px] px-1.5 py-0.5 uppercase tracking-[0.08em]" style={{ color, background: `${color}1a`, border: `1px solid ${color}55` }}>
              {LAYER_LABEL[model.layer]}
            </span>
            <span className="rounded-[4px] border border-[var(--color-border)] px-1.5 py-0.5 text-[var(--color-text-muted)]">{model.materialized}</span>
            {model.tags.map((t) => (
              <span key={t} className="rounded-[4px] border border-[var(--color-border)] px-1.5 py-0.5 text-[var(--color-text-dim)]">#{t}</span>
            ))}
          </div>
        </div>
        <button type="button" onClick={onClose} className="text-[var(--color-text-dim)] hover:text-[var(--color-text)]" aria-label="Close inspector">
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-3">
        <div className="font-mono text-[10px] text-[var(--color-text-dim)]">
          {[model.database, model.schema, model.name].filter(Boolean).join(".")}
        </div>
        {model.description && (
          <p className="text-[11px] leading-5 text-[var(--color-text-muted)]">{model.description}</p>
        )}
        {model.columns.length > 0 && (
          <div>
            <div className="mb-1 text-[9px] uppercase tracking-[0.1em] text-[var(--color-text-dim)]">
              columns ({model.columns.length})
            </div>
            <div className="max-h-48 overflow-y-auto rounded-[8px] border border-[var(--color-border)] bg-[var(--color-bg-input)]">
              {model.columns.map((c) => (
                <div key={c.name} className="border-b border-[var(--color-border)] px-2 py-1 font-mono text-[10px] text-[var(--color-text-muted)] last:border-b-0" title={c.description}>
                  {c.name}
                </div>
              ))}
            </div>
          </div>
        )}
        {model.tests.length > 0 && (
          <div>
            <div className="mb-1 text-[9px] uppercase tracking-[0.1em] text-[var(--color-text-dim)]">
              tests ({model.tests.length})
            </div>
            <div className="flex flex-col gap-px">
              {model.tests.map((t, i) => (
                <div key={`${t.name}-${i}`} className="flex items-center gap-1.5 px-1.5 py-0.5 font-mono text-[10px] text-[var(--color-text-muted)]">
                  <span className="text-[var(--color-success)]" aria-hidden="true">✓</span>
                  <span className="truncate">{t.type}{t.column ? `(${t.column})` : ""}</span>
                </div>
              ))}
            </div>
          </div>
        )}
        {relList(model.parents, "upstream")}
        {relList(model.children, "downstream")}
      </div>
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

export function DbtMapPage() {
  const { toast } = useToast();
  const [projects, setProjects] = useState<WorkspaceProjectInfo[]>([]);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [mapInfo, setMapInfo] = useState<DbtMapInfo | null>(null);
  const [mapStatus, setMapStatus] = useState<string>("loading");
  const [parsed, setParsed] = useState<ParsedMap | null>(null);
  const [visibleLayers, setVisibleLayers] = useState<Set<MapLayer>>(new Set(LAYER_ORDER));
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [focusId, setFocusId] = useState<string | null>(null);
  const [compiling, setCompiling] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);
  const lastUpdatedRef = useRef<number>(0);

  const project = projects.find((p) => p.id === projectId) ?? null;
  const watched: string[] =
    (project?.settings?.watched_branches as string[] | undefined) ??
    (project ? [project.default_branch || "main"] : []);

  // Projects bootstrap; remember the last choice.
  useEffect(() => {
    getWorkspaceProjects("active")
      .then(({ projects: list }) => {
        setProjects(list);
        const remembered = localStorage.getItem("sp:lineage-project");
        const pick = list.find((p) => p.id === remembered) ?? list[0];
        if (pick) setProjectId(pick.id);
        else setMapStatus("no-projects");
      })
      .catch(() => setMapStatus("error"));
  }, []);

  const loadMap = useCallback(
    async (pid: string, { quiet = false } = {}) => {
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
    },
    [],
  );

  useEffect(() => {
    if (!projectId) return;
    localStorage.setItem("sp:lineage-project", projectId);
    setSelectedId(null);
    setFocusId(null);
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

  // Keyboard: "/" focuses search, Escape unwinds focus -> selection.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "/" && document.activeElement?.tagName !== "INPUT") {
        e.preventDefault();
        searchRef.current?.focus();
      } else if (e.key === "Escape") {
        if (focusId) setFocusId(null);
        else setSelectedId(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [focusId]);

  const compileNow = async () => {
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
  };

  const selected = selectedId && parsed ? parsed.models.get(selectedId) ?? null : null;

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      {/* ── Header ── */}
      <div className="flex items-center gap-4 border-b border-[var(--color-border)] bg-[var(--color-bg-card)]/40 px-5 py-2.5">
        <div className="flex items-baseline gap-2">
          <h1 className="text-sm font-bold lowercase text-[var(--color-text)]">dbt map</h1>
          <span className="text-[10px] text-[var(--color-text-dim)]">lineage</span>
        </div>

        <select
          value={projectId ?? ""}
          onChange={(e) => setProjectId(e.target.value)}
          className="rounded-[8px] border border-[var(--color-border)] bg-[var(--color-bg-input)] px-2 py-1 font-mono text-[11px] text-[var(--color-text)] focus:outline-none"
          aria-label="Project"
        >
          {projects.map((p) => (
            <option key={p.id} value={p.id}>{p.display_name || p.name}</option>
          ))}
        </select>

        <div className="relative">
          <Search className="absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-[var(--color-text-dim)]" />
          <input
            ref={searchRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="search models…  /"
            className="w-52 rounded-[8px] border border-[var(--color-border)] bg-[var(--color-bg-input)] py-1 pl-7 pr-2 font-mono text-[11px] text-[var(--color-text)] placeholder:text-[var(--color-text-dim)] focus:border-[var(--color-border-hover)] focus:outline-none"
          />
        </div>

        {focusId && parsed && (
          <button
            type="button"
            onClick={() => setFocusId(null)}
            className="flex items-center gap-1.5 rounded-[8px] border border-[var(--color-border-active)] px-2 py-1 text-[10px] text-[var(--color-text)] hover:bg-[var(--color-bg-hover)]"
          >
            <Crosshair className="h-3 w-3" />
            focused: {parsed.models.get(focusId)?.name} <X className="h-3 w-3" />
          </button>
        )}

        <div className="ml-auto flex items-center gap-3">
          {mapInfo && (
            <span className="hidden items-center gap-1.5 font-mono text-[10px] text-[var(--color-text-dim)] lg:flex">
              {mapStatus === "running" || mapStatus === "queued" ? (
                <>
                  <Loader2 className="h-3 w-3 animate-spin text-[var(--color-warning)]" />
                  compiling on sandbox…
                </>
              ) : (
                <>
                  compiled {timeAgo(mapInfo.updated_at)} · {mapInfo.trigger} · rev {mapInfo.revision}
                  {mapInfo.dbt_version ? ` · dbt ${mapInfo.dbt_version}` : ""}
                </>
              )}
            </span>
          )}
          {watched.length > 0 && (
            <span
              className="flex items-center gap-1.5 rounded-full border border-[var(--color-border)] px-2 py-1 text-[9px] uppercase tracking-[0.08em] text-[var(--color-text-dim)]"
              title={`This map recompiles automatically on pushes to: ${watched.join(", ")}`}
            >
              <span className="relative flex h-1.5 w-1.5">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[var(--color-success)] opacity-60" />
                <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-[var(--color-success)]" />
              </span>
              auto · push → {watched.join(", ")}
            </span>
          )}
          <button
            type="button"
            onClick={() => void compileNow()}
            disabled={compiling || mapStatus === "running"}
            className="flex items-center gap-1.5 rounded-[8px] border border-[var(--color-border)] px-2.5 py-1 text-[10px] text-[var(--color-text)] hover:border-[var(--color-border-hover)] disabled:opacity-40"
          >
            {compiling || mapStatus === "running" ? <RefreshCw className="h-3 w-3 animate-spin" /> : <Hammer className="h-3 w-3" />}
            compile
          </button>
        </div>
      </div>

      {/* ── Body ── */}
      <div className="flex min-h-0 flex-1">
        {parsed && (
          <SchemaWindow
            parsed={parsed}
            query={query}
            selectedId={selectedId}
            onSelect={(id) => {
              setSelectedId(id);
            }}
          />
        )}

        <div className="relative min-w-0 flex-1 bg-[var(--color-bg)]">
          {parsed ? (
            <ReactFlowProvider>
              <MapCanvas
                parsed={parsed}
                visibleLayers={visibleLayers}
                query={query}
                selectedId={selectedId}
                focusId={focusId}
                onSelect={setSelectedId}
                onFocus={(id) => setFocusId((prev) => (prev === id ? null : id))}
              />
            </ReactFlowProvider>
          ) : (
            <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
              {mapStatus === "loading" ? (
                <Loader2 className="h-5 w-5 animate-spin text-[var(--color-text-dim)]" />
              ) : mapStatus === "running" || mapStatus === "queued" ? (
                <>
                  <Loader2 className="h-5 w-5 animate-spin text-[var(--color-warning)]" />
                  <p className="text-xs text-[var(--color-text-muted)]">compiling the dbt map on a sandbox…</p>
                  <p className="text-[10px] text-[var(--color-text-dim)]">this page updates itself when it lands</p>
                </>
              ) : mapStatus === "failed" ? (
                <>
                  <p className="text-xs text-[var(--color-error)]">last compile failed</p>
                  <p className="max-w-md font-mono text-[10px] text-[var(--color-text-dim)]">{mapInfo?.error}</p>
                  <button type="button" onClick={() => void compileNow()} className="rounded-[8px] border border-[var(--color-border)] px-3 py-1.5 text-[11px] text-[var(--color-text)] hover:border-[var(--color-border-hover)]">
                    retry compile
                  </button>
                </>
              ) : mapStatus === "no-projects" ? (
                <p className="text-xs text-[var(--color-text-dim)]">no projects yet — link a GitHub repo to get started</p>
              ) : (
                <>
                  <p className="text-xs text-[var(--color-text-muted)]">no dbt map compiled for this project yet</p>
                  <button type="button" onClick={() => void compileNow()} disabled={compiling} className="flex items-center gap-1.5 rounded-[8px] border border-[var(--color-border)] px-3 py-1.5 text-[11px] text-[var(--color-text)] hover:border-[var(--color-border-hover)] disabled:opacity-50">
                    <Hammer className="h-3 w-3" /> compile dbt map
                  </button>
                  <p className="text-[10px] text-[var(--color-text-dim)]">runs dbt parse on a sandbox — no warehouse access needed</p>
                </>
              )}
            </div>
          )}

          {/* ── Legend / layer filter (fixed order — identity, never cycled) ── */}
          {parsed && (
            <div className="absolute bottom-3 left-3 rounded-[10px] border border-[var(--color-border)] bg-[var(--color-bg-card)]/90 p-2 backdrop-blur">
              {LAYER_ORDER.map((layer) => {
                const count = parsed.layerCounts[layer];
                if (count === 0) return null;
                const on = visibleLayers.has(layer);
                return (
                  <button
                    key={layer}
                    type="button"
                    onClick={() =>
                      setVisibleLayers((prev) => {
                        const next = new Set(prev);
                        if (next.has(layer)) next.delete(layer);
                        else next.add(layer);
                        return next;
                      })
                    }
                    className={`flex w-full items-center gap-2 rounded px-1.5 py-[3px] text-left text-[10px] transition-opacity ${on ? "" : "opacity-35"} hover:bg-[var(--color-bg-hover)]`}
                    aria-pressed={on}
                  >
                    <span className="h-2 w-2 rounded-[3px]" style={{ background: LAYER_COLOR[layer] }} aria-hidden="true" />
                    <span className="text-[var(--color-text-muted)]">{LAYER_LABEL[layer]}</span>
                    <span className="ml-auto font-mono text-[9px] text-[var(--color-text-dim)]">{count}</span>
                  </button>
                );
              })}
              <div className="mt-1 border-t border-[var(--color-border)] px-1.5 pt-1 font-mono text-[9px] text-[var(--color-text-dim)]">
                {parsed.models.size} nodes · {parsed.edges.length} edges
              </div>
            </div>
          )}
        </div>

        {selected && parsed && (
          <Inspector
            parsed={parsed}
            model={selected}
            onClose={() => setSelectedId(null)}
            onNavigate={(id) => setSelectedId(id)}
          />
        )}
      </div>
    </div>
  );
}
