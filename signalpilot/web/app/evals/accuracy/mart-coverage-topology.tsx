"use client";

import { memo, useCallback, useEffect, useMemo, useState } from "react";
import {
  Database,
  FileCheck2,
  FlaskConical,
  LocateFixed,
  Search,
  Table2,
  X,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import ReactFlow, {
  Background,
  BackgroundVariant,
  Handle,
  MiniMap,
  Position,
  ReactFlowProvider,
  type Edge,
  type Node,
  type NodeProps,
  useReactFlow,
} from "reactflow";
import "reactflow/dist/style.css";
import type { EvalCoverageModel, EvalTask } from "~/lib/api";

type CoverageFilter = "all" | "covered" | "gaps";
type CoverageState = "task" | "covered" | "none";
type CoverageNodeData = {
  kind: "task" | "mart";
  label: string;
  meta: string;
  state: CoverageState;
  selected: boolean;
  dimmed: boolean;
};

const TASK_WIDTH = 220;
const TASK_HEIGHT = 58;
const MART_WIDTH = 240;
const MART_HEIGHT = 52;
const LANE_GAP = 280;
const ROW_GAP = 66;
const TARGET_LANE_ROWS = 12;
const MAX_LANES = 10;

function modelState(model: EvalCoverageModel): CoverageState {
  return model.covered ? "covered" : "none";
}

function laneCountFor(modelCount: number): number {
  return Math.min(MAX_LANES, Math.max(1, Math.ceil(modelCount / TARGET_LANE_ROWS)));
}

const CoverageNode = memo(function CoverageNode({ data }: NodeProps<CoverageNodeData>) {
  const Icon = data.kind === "task" ? FlaskConical : Table2;
  return (
    <div
      className={`acc-topology-node is-${data.kind} is-${data.state}${data.selected ? " is-selected" : ""}${data.dimmed ? " is-dimmed" : ""}`}
    >
      {data.kind === "mart" && <Handle type="target" position={Position.Left} className="acc-topology-handle" />}
      <Icon aria-hidden="true" />
      <div>
        <strong>{data.label}</strong>
        <span>{data.meta}</span>
      </div>
      {data.kind === "task" && <Handle type="source" position={Position.Right} className="acc-topology-handle" />}
    </div>
  );
});

const nodeTypes = { coverage: CoverageNode };

function lanePositions(models: EvalCoverageModel[], startX: number): Map<string, { x: number; y: number }> {
  const positions = new Map<string, { x: number; y: number }>();
  if (!models.length) return positions;
  const laneCount = laneCountFor(models.length);
  const rows = Math.ceil(models.length / laneCount);
  models.forEach((model, index) => {
    const lane = Math.floor(index / rows);
    const row = index % rows;
    positions.set(model.name, { x: startX + lane * LANE_GAP, y: 38 + row * ROW_GAP });
  });
  return positions;
}

function MartCoverageTopologyCanvas({ models, tasks }: { models: EvalCoverageModel[]; tasks: EvalTask[] }) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<CoverageFilter>("covered");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const flow = useReactFlow();
  const taskMap = useMemo(() => new Map(tasks.map((task) => [task.id, task])), [tasks]);
  const marts = useMemo(() => models.filter((model) => model.layer === "marts"), [models]);
  const coveredCount = useMemo(() => marts.filter((model) => model.covered).length, [marts]);

  const filteredMarts = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const matchingTasks = new Set(
      tasks
        .filter((task) => task.id.toLowerCase().includes(needle) || task.title.toLowerCase().includes(needle))
        .map((task) => task.id),
    );
    return marts.filter((model) => {
      if (filter === "covered" && !model.covered) return false;
      if (filter === "gaps" && model.covered) return false;
      if (!needle) return true;
      if (model.name.toLowerCase().includes(needle)) return true;
      return [...model.declared_by, ...model.observed_by].some((taskId) => matchingTasks.has(taskId));
    });
  }, [filter, marts, query, tasks]);

  const visibleTaskIds = useMemo(() => {
    const ids = new Set<string>();
    filteredMarts.forEach((model) => {
      model.declared_by.forEach((id) => ids.add(id));
      model.observed_by.forEach((id) => ids.add(id));
    });
    return [...ids].sort((left, right) => {
      const leftLabel = taskMap.get(left)?.title ?? left;
      const rightLabel = taskMap.get(right)?.title ?? right;
      return leftLabel.localeCompare(rightLabel);
    });
  }, [filteredMarts, taskMap]);

  const selectedRelations = useMemo(() => {
    const ids = new Set<string>();
    if (!selectedId) return ids;
    ids.add(selectedId);
    if (selectedId.startsWith("task:")) {
      const taskId = selectedId.slice(5);
      filteredMarts.forEach((model) => {
        if (model.declared_by.includes(taskId) || model.observed_by.includes(taskId)) ids.add(`mart:${model.name}`);
      });
    } else if (selectedId.startsWith("mart:")) {
      const model = marts.find((item) => item.name === selectedId.slice(5));
      model?.declared_by.forEach((id) => ids.add(`task:${id}`));
      model?.observed_by.forEach((id) => ids.add(`task:${id}`));
    }
    return ids;
  }, [filteredMarts, marts, selectedId]);

  const graph = useMemo(() => {
    const coveredModels = filteredMarts
      .filter((model) => model.covered)
      .sort((left, right) => {
        const leftKey = [...new Set([...left.declared_by, ...left.observed_by])].sort().join("|");
        const rightKey = [...new Set([...right.declared_by, ...right.observed_by])].sort().join("|");
        return leftKey.localeCompare(rightKey) || left.name.localeCompare(right.name);
      });
    const gapModels = filteredMarts.filter((model) => !model.covered).sort((left, right) => left.name.localeCompare(right.name));
    const coveredLaneCount = coveredModels.length ? laneCountFor(coveredModels.length) : 0;
    const gapLaneCount = gapModels.length ? laneCountFor(gapModels.length) : 0;
    const coveredPositions = lanePositions(coveredModels, 440);
    const gapPositions = lanePositions(gapModels, 440 + coveredLaneCount * LANE_GAP + (coveredLaneCount ? 80 : 0));
    const maxRows = Math.max(
      1,
      Math.ceil(coveredModels.length / Math.max(coveredLaneCount, 1)),
      Math.ceil(gapModels.length / Math.max(gapLaneCount, 1)),
    );
    const graphHeight = Math.max(360, maxRows * ROW_GAP, visibleTaskIds.length * (TASK_HEIGHT + 18));
    const hasSelection = selectedRelations.size > 0;
    const nodes: Node<CoverageNodeData>[] = [];

    visibleTaskIds.forEach((taskId, index) => {
      const task = taskMap.get(taskId);
      const linkedCount = filteredMarts.filter(
        (model) => model.declared_by.includes(taskId) || model.observed_by.includes(taskId),
      ).length;
      const nodeId = `task:${taskId}`;
      nodes.push({
        id: nodeId,
        type: "coverage",
        position: {
          x: 40,
          y: ((index + 0.5) / Math.max(visibleTaskIds.length, 1)) * graphHeight - TASK_HEIGHT / 2,
        },
        style: { width: TASK_WIDTH, height: TASK_HEIGHT },
        width: TASK_WIDTH,
        height: TASK_HEIGHT,
        data: {
          kind: "task",
          label: task?.title ?? taskId,
          meta: `${linkedCount} ${linkedCount === 1 ? "mart" : "marts"}`,
          state: "task",
          selected: selectedId === nodeId,
          dimmed: hasSelection && !selectedRelations.has(nodeId),
        },
      });
    });

    [...coveredModels, ...gapModels].forEach((model) => {
      const position = coveredPositions.get(model.name) ?? gapPositions.get(model.name)!;
      const state = modelState(model);
      const nodeId = `mart:${model.name}`;
      const linkCount = new Set([...model.declared_by, ...model.observed_by]).size;
      nodes.push({
        id: nodeId,
        type: "coverage",
        position,
        style: { width: MART_WIDTH, height: MART_HEIGHT },
        width: MART_WIDTH,
        height: MART_HEIGHT,
        data: {
          kind: "mart",
          label: model.name,
          meta: linkCount ? `${linkCount} ${linkCount === 1 ? "eval task" : "eval tasks"}` : "coverage gap",
          state,
          selected: selectedId === nodeId,
          dimmed: hasSelection && !selectedRelations.has(nodeId),
        },
      });
    });

    const edges: Edge[] = [];
    coveredModels.forEach((model) => {
      const taskIds = [...new Set([...model.declared_by, ...model.observed_by])];
      taskIds.forEach((taskId) => {
        const source = `task:${taskId}`;
        const target = `mart:${model.name}`;
        const related = !hasSelection || (selectedRelations.has(source) && selectedRelations.has(target));
        edges.push({
          id: `${source}->${target}`,
          source,
          target,
          type: "smoothstep",
          style: {
            stroke: "#49a078",
            strokeWidth: related && hasSelection ? 2 : 1,
            opacity: related ? (hasSelection ? 0.9 : 0.2) : 0.025,
          },
        });
      });
    });
    return { nodes, edges };
  }, [filteredMarts, selectedId, selectedRelations, taskMap, visibleTaskIds]);

  const graphKey = `${filter}:${query}:${filteredMarts.map((model) => model.name).join("|")}`;
  const visibleNodeIds = useMemo(
    () => new Set([
      ...visibleTaskIds.map((taskId) => `task:${taskId}`),
      ...filteredMarts.map((model) => `mart:${model.name}`),
    ]),
    [filteredMarts, visibleTaskIds],
  );
  useEffect(() => {
    setSelectedId((current) => current && visibleNodeIds.has(current) ? current : null);
    const timer = window.setTimeout(() => flow.fitView({ padding: 0.12, duration: 450 }), 50);
    return () => window.clearTimeout(timer);
  }, [flow, graphKey, visibleNodeIds]);

  const selectedModel = selectedId?.startsWith("mart:")
    ? marts.find((model) => model.name === selectedId.slice(5)) ?? null
    : null;
  const selectedTaskId = selectedId?.startsWith("task:") ? selectedId.slice(5) : null;
  const selectedTask = selectedTaskId ? taskMap.get(selectedTaskId) : null;
  const selectedModelTaskIds = selectedModel
    ? [...new Set([...selectedModel.declared_by, ...selectedModel.observed_by])]
    : [];
  const selectedTaskModels = selectedTaskId
    ? marts.filter((model) => model.declared_by.includes(selectedTaskId) || model.observed_by.includes(selectedTaskId))
    : [];

  const focusNode = useCallback((node: Node<CoverageNodeData>) => {
    setSelectedId((current) => current === node.id ? null : node.id);
  }, []);

  return (
    <>
      <div className="acc-section-head acc-topology-heading">
        <div>
          <span className="acc-eyebrow">Coverage topology</span>
          <h2>Which tests protect each mart</h2>
          <p>{coveredCount} of {marts.length} marts are covered by at least one eval task.</p>
        </div>
        <div className="acc-topology-tools">
          <div className="acc-segments" aria-label="Filter mart coverage">
            {(["all", "covered", "gaps"] as const).map((value) => (
              <button key={value} className={filter === value ? "is-on" : ""} onClick={() => setFilter(value)}>
                {value}
              </button>
            ))}
          </div>
          <div className="acc-search acc-topology-search">
            <Search aria-hidden="true" />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Find a mart or task" aria-label="Find a mart or task" />
            {query && <button onClick={() => setQuery("")} aria-label="Clear search" title="Clear search"><X /></button>}
          </div>
        </div>
      </div>

      <div className="acc-coverage-summary">
        <div className="acc-coverage-number"><strong>{marts.length ? Math.round(coveredCount / marts.length * 100) : 0}%</strong><span>mart coverage</span></div>
        <div className="acc-coverage-track"><span style={{ width: `${marts.length ? coveredCount / marts.length * 100 : 0}%` }} /></div>
        <div className="acc-legend">
          <span><i className="covered" /> covered</span>
          <span><i className="uncovered" /> not covered</span>
        </div>
      </div>

      <div className="acc-topology-shell">
        <div className="acc-topology-status">
          <span><FlaskConical /> {visibleTaskIds.length} tasks</span>
          <span><Database /> {filteredMarts.length} marts</span>
          <span><FileCheck2 /> {graph.edges.length} links</span>
        </div>
        <div className="acc-topology-canvas" aria-label="Eval task and mart coverage topology">
          <ReactFlow
            nodes={graph.nodes}
            edges={graph.edges}
            nodeTypes={nodeTypes}
            onNodeClick={(_event, node) => focusNode(node)}
            onPaneClick={() => setSelectedId(null)}
            nodesDraggable={false}
            nodesConnectable={false}
            elementsSelectable
            fitView
            fitViewOptions={{ padding: 0.12 }}
            minZoom={0.08}
            maxZoom={2.25}
            zoomOnDoubleClick={false}
            proOptions={{ hideAttribution: true }}
          >
            <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="var(--color-border-hover)" />
            <MiniMap
              position="bottom-left"
              pannable
              zoomable
              nodeColor={(node) => {
                const data = node.data as CoverageNodeData;
                if (data.kind === "task") return "#6e91be";
                return data.state === "covered" ? "#49a078" : "#8a6d73";
              }}
              maskColor="color-mix(in srgb, var(--color-bg) 78%, transparent)"
            />
          </ReactFlow>

          <div className="acc-canvas-controls" aria-label="Topology zoom controls">
            <button onClick={() => flow.zoomIn({ duration: 180 })} aria-label="Zoom in" title="Zoom in"><ZoomIn /></button>
            <button onClick={() => flow.zoomOut({ duration: 180 })} aria-label="Zoom out" title="Zoom out"><ZoomOut /></button>
            <button onClick={() => flow.fitView({ padding: 0.12, duration: 350 })} aria-label="Fit topology" title="Fit topology"><LocateFixed /></button>
          </div>

          {!graph.nodes.length && (
            <div className="acc-topology-empty">
              <Search />
              <strong>No matching topology</strong>
              <span>Adjust the search or coverage filter.</span>
            </div>
          )}

          {(selectedModel || selectedTaskId) && (
            <aside className="acc-topology-detail">
              <button className="acc-topology-close" onClick={() => setSelectedId(null)} aria-label="Close topology details" title="Close"><X /></button>
              {selectedModel ? (
                <>
                  <span className="acc-eyebrow">Mart</span>
                  <h3>{selectedModel.name}</h3>
                  <div className={`acc-topology-state is-${modelState(selectedModel)}`}><i /> {selectedModel.covered ? "Covered" : "Not covered"}</div>
                  <dl>
                    <div><dt>Coverage</dt><dd>{selectedModel.covered ? "Covered" : "Not covered"}</dd></div>
                    <div><dt>Eval tasks</dt><dd>{selectedModelTaskIds.length}</dd></div>
                  </dl>
                  <div className="acc-topology-relations">
                    {selectedModelTaskIds.map((taskId) => (
                      <button key={taskId} onClick={() => setSelectedId(`task:${taskId}`)}>
                        <FlaskConical />
                        <span><strong>{taskMap.get(taskId)?.title ?? taskId}</strong><small>Covers this mart</small></span>
                      </button>
                    ))}
                    {!selectedModel.covered && <p>No eval task covers this mart.</p>}
                  </div>
                </>
              ) : (
                <>
                  <span className="acc-eyebrow">Eval task</span>
                  <h3>{selectedTask?.title ?? selectedTaskId}</h3>
                  <code>{selectedTaskId}</code>
                  <dl>
                    <div><dt>Protected marts</dt><dd>{selectedTaskModels.length}</dd></div>
                    <div><dt>Task class</dt><dd>{selectedTask?.class ?? "unknown"}</dd></div>
                  </dl>
                  <div className="acc-topology-relations">
                    {selectedTaskModels.map((model) => (
                      <button key={model.name} onClick={() => setSelectedId(`mart:${model.name}`)}>
                        <Table2 />
                        <span><strong>{model.name}</strong><small>Covered</small></span>
                      </button>
                    ))}
                  </div>
                </>
              )}
            </aside>
          )}
        </div>
      </div>
    </>
  );
}

export function MartCoverageTopology({ models, tasks }: { models: EvalCoverageModel[]; tasks: EvalTask[] }) {
  const marts = models.filter((model) => model.layer === "marts");
  if (!marts.length) {
    return (
      <section className="acc-section acc-empty">
        <Table2 />
        <div>
          <h2>Mart coverage map</h2>
          <p>Complete a run with a connected dbt project to map marts to the tasks that declare or observe them.</p>
        </div>
      </section>
    );
  }
  return (
    <section className="acc-section">
      <ReactFlowProvider>
        <MartCoverageTopologyCanvas models={models} tasks={tasks} />
      </ReactFlowProvider>
    </section>
  );
}
