"use client";

/**
 * The dbt map canvas. Two layout modes:
 *  - full map: dagre left-to-right over the whole graph;
 *  - focus mode: the focused model's lineage cone in labeled stage columns
 *    (Sources → Staging → Intermediate → Dims/Facts → Marts), laid out
 *    deterministically with barycenter row ordering so revisits look the same.
 */

import React, { memo, useEffect, useMemo, useRef, useState } from "react";
import ReactFlow, {
  Background,
  BackgroundVariant,
  Controls,
  type Edge,
  MarkerType,
  MiniMap,
  type Node,
  type NodeProps,
  useReactFlow,
} from "reactflow";
import { graphlib, layout as dagreLayout } from "@dagrejs/dagre";

import { LAYER_COLOR } from "./palette";
import type { MapLayer } from "./palette";
import { MapNode, NODE_H, NODE_W, type MapNodeData, mapNodeTypes } from "./map-node";
import { lineageCone, type MapModel, type ParsedMap } from "./parse-map";
import { stageColumns } from "./lineage-nav";

// Staged (focus) layout metrics. Edges are simple left-to-right bezier runs,
// so columns can sit close; the taller row gap lets small cones fill the
// frame vertically instead of letterboxing.
const COL_GAP = 100;
const ROW_GAP = 40;

// Camera readability floors: below these zooms, labels are unreadable dust.
const LANDING_MIN_ZOOM = 0.5;
const LANDING_MAX_ZOOM = 0.85;
const FOCUS_MIN_ZOOM = 0.65;

function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(mq.matches);
    const onChange = (e: MediaQueryListEvent) => setReduced(e.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return reduced;
}

// ── Layouts ──────────────────────────────────────────────────────────────────

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

interface StageCaption {
  label: string;
  count: number;
  x: number;
  y: number;
}

/**
 * Manual column layout for a focus cone: x fixed per stage, rows ordered by
 * two barycenter sweeps over parent positions (deterministic; ties by name).
 */
function layoutStaged(
  parsed: ParsedMap,
  ids: Set<string>,
  edges: { source: string; target: string }[],
): { positions: Map<string, { x: number; y: number }>; captions: StageCaption[] } {
  const { stages, columnOf } = stageColumns(parsed, ids);
  const order = stages.map((s) => [...s.ids]);

  const parentsOf = new Map<string, string[]>();
  for (const e of edges) {
    if (!parentsOf.has(e.target)) parentsOf.set(e.target, []);
    parentsOf.get(e.target)!.push(e.source);
  }
  const rowIndex = new Map<string, number>();
  const reindex = () =>
    order.forEach((col) => col.forEach((id, i) => rowIndex.set(id, i)));
  reindex();
  for (let sweep = 0; sweep < 2; sweep++) {
    for (let c = 1; c < order.length; c++) {
      const scored = order[c].map((id) => {
        const ps = (parentsOf.get(id) ?? []).map((p) => rowIndex.get(p)).filter((v): v is number => v !== undefined);
        const bary = ps.length ? ps.reduce((a, b) => a + b, 0) / ps.length : rowIndex.get(id)!;
        return { id, bary };
      });
      scored.sort((a, b) => a.bary - b.bary || a.id.localeCompare(b.id));
      order[c] = scored.map((s) => s.id);
      reindex();
    }
  }

  const tallest = Math.max(1, ...order.map((col) => col.length));
  const totalH = tallest * NODE_H + (tallest - 1) * ROW_GAP;
  const positions = new Map<string, { x: number; y: number }>();
  const captions: StageCaption[] = [];
  order.forEach((col, c) => {
    const x = c * (NODE_W + COL_GAP);
    const colH = col.length * NODE_H + (col.length - 1) * ROW_GAP;
    const yStart = (totalH - colH) / 2;
    col.forEach((id, r) => positions.set(id, { x, y: yStart + r * (NODE_H + ROW_GAP) }));
    captions.push({ label: stages[c].label, count: col.length, x, y: -84 });
  });
  return { positions, captions };
}

// ── Stage caption node ───────────────────────────────────────────────────────

function StageCaptionInner({ data }: NodeProps<{ label: string; count: number }>) {
  return (
    <div className="pointer-events-none select-none" style={{ width: NODE_W }}>
      <div className="flex items-baseline gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--color-text-muted)]">
          {data.label}
        </span>
        <span className="font-mono text-[9px] tabular-nums text-[var(--color-text-dim)]">
          {data.count}
        </span>
      </div>
      <div className="mt-1.5 h-px w-full bg-gradient-to-r from-[var(--color-border-hover)] to-transparent" />
    </div>
  );
}
const StageCaptionNode = memo(StageCaptionInner);
const nodeTypes = { ...mapNodeTypes, stageCaption: StageCaptionNode };

// ── Canvas ───────────────────────────────────────────────────────────────────

export function MapCanvas({
  parsed,
  visibleLayers,
  query,
  selectedId,
  focusId,
  highlightIds,
  onSelect,
  onFocus,
}: {
  parsed: ParsedMap;
  visibleLayers: Set<MapLayer>;
  query: string;
  selectedId: string | null;
  focusId: string | null;
  /** External path highlight (Raw Tables hover) — overrides selection/hover. */
  highlightIds: Set<string> | null;
  onSelect: (id: string | null) => void;
  onFocus: (id: string | null) => void;
}) {
  const api = useReactFlow();
  const reducedMotion = usePrefersReducedMotion();
  const [hoverId, setHoverId] = useState<string | null>(null);
  const [initTick, setInitTick] = useState(0);

  const focusCone = useMemo(
    () => (focusId && parsed.models.has(focusId) ? lineageCone(parsed, focusId) : null),
    [parsed, focusId],
  );

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    const ids = new Set<string>();
    for (const m of parsed.models.values()) {
      // Focus mode tells the whole staged story of the cone: layer toggles
      // (full-map chrome) never silently delete a stage column here.
      if (!focusCone && !visibleLayers.has(m.layer)) continue;
      if (q && !m.name.toLowerCase().includes(q) && !m.schema.toLowerCase().includes(q)) continue;
      if (focusCone && !focusCone.has(m.id)) continue;
      ids.add(m.id);
    }
    return ids;
  }, [parsed, visibleLayers, query, focusCone]);

  const visibleEdges = useMemo(
    () => parsed.edges.filter((e) => visible.has(e.source) && visible.has(e.target)),
    [parsed, visible],
  );

  const staged = useMemo(
    () => (focusCone ? layoutStaged(parsed, visible, visibleEdges) : null),
    [parsed, focusCone, visible, visibleEdges],
  );

  const positions = useMemo(() => {
    if (staged) return staged.positions;
    const models = [...visible].map((id) => parsed.models.get(id)!);
    return layoutNodes(models, visibleEdges);
  }, [parsed, visible, visibleEdges, staged]);

  // Cross-fade on focus enter/exit: nodes that just left the visible set stay
  // mounted for one transition beat at opacity 0 (at their old positions)
  // instead of popping out in a single frame. The entrance side is the mount
  // fade in map-node.tsx.
  const prevViewRef = useRef<{ visible: Set<string>; positions: Map<string, { x: number; y: number }> } | null>(null);
  const [leaving, setLeaving] = useState<Map<string, { x: number; y: number }>>(new Map());
  useEffect(() => {
    const prev = prevViewRef.current;
    prevViewRef.current = { visible, positions };
    const gone = new Map<string, { x: number; y: number }>();
    if (prev && !reducedMotion) {
      for (const id of prev.visible) {
        if (visible.has(id)) continue;
        const p = prev.positions.get(id);
        if (p) gone.set(id, p);
      }
    }
    setLeaving((cur) => (cur.size === 0 && gone.size === 0 ? cur : gone));
    if (gone.size === 0) return;
    const t = setTimeout(() => setLeaving(new Map()), 260);
    return () => clearTimeout(t);
  }, [visible, positions, reducedMotion]);

  // The active lineage path: external highlight > selection > hover.
  const pathCone = useMemo(() => {
    if (highlightIds) return highlightIds;
    const anchor = selectedId ?? hoverId;
    if (!anchor || !visible.has(anchor)) return null;
    return lineageCone(parsed, anchor);
  }, [parsed, selectedId, hoverId, visible, highlightIds]);

  const rfNodes: Node[] = useMemo(() => {
    const nodes: Node[] = [...visible].map((id) => {
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
          focusRoot: id === focusId,
        } satisfies MapNodeData,
      };
    });
    for (const [id, pos] of leaving) {
      if (visible.has(id)) continue;
      const model = parsed.models.get(id);
      if (!model) continue;
      nodes.push({
        id,
        type: "dbtMap",
        position: pos,
        width: NODE_W,
        height: NODE_H,
        selectable: false,
        draggable: false,
        focusable: false,
        style: { pointerEvents: "none" },
        data: { model, onPath: null, selected: false, leaving: true } satisfies MapNodeData,
      });
    }
    if (staged) {
      for (const cap of staged.captions) {
        nodes.push({
          id: `stage:${cap.label}`,
          type: "stageCaption",
          position: { x: cap.x, y: cap.y },
          selectable: false,
          draggable: false,
          focusable: false,
          data: { label: cap.label, count: cap.count },
        });
      }
    }
    return nodes;
  }, [parsed, visible, positions, pathCone, selectedId, focusId, staged, leaving]);

  const rfEdges: Edge[] = useMemo(
    () =>
      visibleEdges.map((e) => {
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
    [parsed, visibleEdges, pathCone],
  );

  // Initial camera. A fit-all (or fit-all-marts) of a big DAG is unreadable
  // dust, so the landing frame is the densest mart/fact cluster at a zoom
  // clamped to a readability floor — the minimap answers "where am I
  // globally". Focus mode frames the cone, floored at FOCUS_MIN_ZOOM so the
  // staged story reads without manual zooming.
  const wrapRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const duration = reducedMotion ? 0 : 400;
    const t = setTimeout(() => {
      const vw = wrapRef.current?.clientWidth ?? 1200;
      const vh = wrapRef.current?.clientHeight ?? 800;
      const boundsOf = (ids: string[]) => {
        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
        for (const id of ids) {
          const p = positions.get(id);
          if (!p) continue;
          minX = Math.min(minX, p.x);
          minY = Math.min(minY, p.y);
          maxX = Math.max(maxX, p.x + NODE_W);
          maxY = Math.max(maxY, p.y + NODE_H);
        }
        return { minX, minY, maxX, maxY };
      };
      // Center the bounds at a zoom clamped to [floor, ceil] — fitBounds
      // can't take a zoom floor, so the clamp goes through setCenter. When
      // the floor makes the content overflow the viewport, `mustSee` (the
      // focus root) is kept fully in frame instead of clipping at an edge.
      const frame = (
        b: { minX: number; minY: number; maxX: number; maxY: number },
        floor: number,
        ceil: number,
        mustSee?: { x: number; y: number },
      ) => {
        const w = Math.max(1, b.maxX - b.minX);
        const h = Math.max(1, b.maxY - b.minY);
        const fit = Math.min((vw * 0.85) / w, (vh * 0.85) / h);
        const zoom = Math.min(Math.max(fit, floor), ceil);
        let cx = b.minX + w / 2;
        if (mustSee) {
          const halfW = vw / (2 * zoom);
          const margin = 24 / zoom;
          cx = Math.max(cx, mustSee.x + NODE_W + margin - halfW);
          cx = Math.min(cx, mustSee.x - margin + halfW);
        }
        api.setCenter(cx, b.minY + h / 2, { zoom, duration });
      };

      const ids = [...visible];
      const all = boundsOf(ids);
      if (!Number.isFinite(all.minX)) {
        api.fitView({ padding: 0.1, duration });
        return;
      }
      if (focusId) {
        // Captions in frame; the focus root never clipped by the zoom floor.
        frame({ ...all, minY: all.minY - 96 }, FOCUS_MIN_ZOOM, 1, positions.get(focusId));
        return;
      }
      if (ids.length > 80) {
        const anchors = ids
          .filter((id) => {
            const layer = parsed.models.get(id)!.layer;
            return layer === "mart" || layer === "fact";
          })
          .map((id) => ({ id, y: positions.get(id)?.y ?? 0 }))
          .sort((a, b) => a.y - b.y);
        if (anchors.length >= 2) {
          // Densest vertical run of marts/facts that fits at the landing floor.
          const windowH = (vh * 0.85) / LANDING_MIN_ZOOM;
          let best = { from: 0, to: 0, count: 1 };
          let from = 0;
          for (let to = 0; to < anchors.length; to++) {
            while (anchors[to].y + NODE_H - anchors[from].y > windowH) from++;
            if (to - from + 1 > best.count) best = { from, to, count: to - from + 1 };
          }
          const cluster = anchors.slice(best.from, best.to + 1).map((a) => a.id);
          frame(boundsOf(cluster), LANDING_MIN_ZOOM, LANDING_MAX_ZOOM);
          return;
        }
      }
      frame(all, 0.05, 1);
    }, 120);
    return () => clearTimeout(t);
  }, [api, parsed, positions, visible, focusId, initTick, reducedMotion]);

  // External selection (schema panel / inspector nav) -> center the node.
  useEffect(() => {
    if (!selectedId) return;
    const p = positions.get(selectedId);
    if (p) {
      api.setCenter(p.x + NODE_W / 2, p.y + NODE_H / 2, {
        zoom: 1,
        duration: reducedMotion ? 0 : 500,
      });
    }
  }, [selectedId, positions, api, reducedMotion]);

  return (
    <div ref={wrapRef} className="h-full w-full">
    <ReactFlow
      nodes={rfNodes}
      edges={rfEdges}
      nodeTypes={nodeTypes}
      onNodeClick={(_, n) => {
        if (n.type !== "dbtMap") return;
        onSelect(n.id === selectedId ? null : n.id);
      }}
      onNodeDoubleClick={(_, n) => {
        if (n.type === "dbtMap") onFocus(n.id);
      }}
      onNodeMouseEnter={(_, n) => setHoverId(n.type === "dbtMap" ? n.id : null)}
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
      {!focusId && (
        <MiniMap
          position="top-right"
          pannable
          zoomable
          className="!h-28 !w-44 !border !border-[var(--color-border)] !bg-[var(--color-bg)]"
          maskColor="rgba(14,14,15,0.75)"
          nodeColor={(n) =>
            n.type === "dbtMap" ? LAYER_COLOR[(n.data as MapNodeData).model.layer] : "transparent"
          }
          nodeStrokeWidth={0}
        />
      )}
    </ReactFlow>
    </div>
  );
}

export { MapNode, NODE_H, NODE_W };
