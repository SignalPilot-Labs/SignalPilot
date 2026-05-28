import { graphlib, layout } from "@dagrejs/dagre";
import React, { useCallback, useEffect, useMemo } from "react";
import ReactFlow, {
  Background,
  BackgroundVariant,
  Controls,
  type Edge,
  MarkerType,
  type Node,
  useEdgesState,
  useNodesState,
  useReactFlow,
} from "reactflow";
import type { DbtNodeData } from "./dbt-lineage-node";
import { dbtNodeTypes } from "./dbt-lineage-node";
import { EDGE_COLORS } from "./layer-colors";
import { ModelDetailPanel } from "./model-detail-panel";
import type {
  DbtLineageData,
  DbtLineageNode,
  LayoutDirection,
  LineageFilterState,
} from "./types";

interface Props {
  data: DbtLineageData;
  layoutDirection: LayoutDirection;
  filter: LineageFilterState;
  selectedNode: DbtLineageNode | null;
  onSelectNode: (node: DbtLineageNode | null) => void;
}

function buildGraphElements(
  data: DbtLineageData,
  filter: LineageFilterState,
  layoutDirection: LayoutDirection,
): { nodes: Node<DbtNodeData>[]; edges: Edge[] } {
  const visibleNodeIds = new Set<string>();
  const query = filter.searchQuery.toLowerCase();

  for (const [id, node] of data.nodes) {
    if (!filter.layers.has(node.layer)) {
      continue;
    }
    if (query && !node.name.toLowerCase().includes(query)) {
      continue;
    }
    visibleNodeIds.add(id);
  }

  const rfNodes: Node<DbtNodeData>[] = [];
  for (const id of visibleNodeIds) {
    const node = data.nodes.get(id)!;
    rfNodes.push({
      id,
      type: "dbtModel",
      data: { node, layoutDirection },
      position: { x: 0, y: 0 },
      width: 240,
      height: 120,
    });
  }

  const rfEdges: Edge[] = [];
  for (const edge of data.edges) {
    if (!visibleNodeIds.has(edge.source) || !visibleNodeIds.has(edge.target)) {
      continue;
    }
    const sourceNode = data.nodes.get(edge.source);
    const color = sourceNode
      ? EDGE_COLORS[sourceNode.layer]
      : EDGE_COLORS.other;

    rfEdges.push({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      sourceHandle: "source",
      targetHandle: "target",
      type: "smoothstep",
      animated: true,
      markerEnd: {
        type: MarkerType.ArrowClosed,
        width: 16,
        height: 16,
        color,
      },
      style: {
        strokeWidth: 2,
        stroke: color,
        opacity: 0.6,
      },
    });
  }

  return layoutGraph(rfNodes, rfEdges, layoutDirection);
}

function layoutGraph(
  nodes: Node<DbtNodeData>[],
  edges: Edge[],
  direction: LayoutDirection,
): { nodes: Node<DbtNodeData>[]; edges: Edge[] } {
  if (nodes.length === 0) {
    return { nodes, edges };
  }

  const g = new graphlib.Graph().setDefaultEdgeLabel(() => ({}));
  g.setGraph({
    rankdir: direction,
    nodesep: 60,
    ranksep: 120,
    ranker: "network-simplex",
    marginx: 40,
    marginy: 40,
  });

  for (const node of nodes) {
    g.setNode(node.id, {
      width: node.width ?? 240,
      height: node.height ?? 120,
    });
  }
  for (const edge of edges) {
    g.setEdge(edge.source, edge.target);
  }

  layout(g);

  const positioned = nodes.map((node) => {
    const pos = g.node(node.id);
    return {
      ...node,
      position: {
        x: pos.x - (node.width ?? 240) / 2,
        y: pos.y - (node.height ?? 120) / 2,
      },
    };
  });

  return { nodes: positioned, edges };
}

export const LineageGraph: React.FC<Props> = ({
  data,
  layoutDirection,
  filter,
  selectedNode,
  onSelectNode,
}) => {
  const elements = useMemo(
    () => buildGraphElements(data, filter, layoutDirection),
    [data, filter, layoutDirection],
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(elements.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(elements.edges);
  const api = useReactFlow();

  useEffect(() => {
    setNodes(elements.nodes);
    setEdges(elements.edges);
    // Fit view after layout change
    setTimeout(() => api.fitView({ padding: 0.15, duration: 400 }), 50);
  }, [elements, setNodes, setEdges, api]);

  const handleNodeClick = useCallback(
    (_event: React.MouseEvent, node: Node<DbtNodeData>) => {
      const lineageNode = data.nodes.get(node.id);
      if (lineageNode) {
        onSelectNode(lineageNode);
      }
    },
    [data, onSelectNode],
  );

  const handlePaneClick = useCallback(() => {
    onSelectNode(null);
  }, [onSelectNode]);

  const handleNavigateToNode = useCallback(
    (nodeId: string) => {
      const lineageNode = data.nodes.get(nodeId);
      if (lineageNode) {
        onSelectNode(lineageNode);
        const rfNode = nodes.find((n) => n.id === nodeId);
        if (rfNode) {
          api.fitView({
            padding: 1,
            duration: 600,
            nodes: [rfNode],
          });
        }
      }
    },
    [data, onSelectNode, nodes, api],
  );

  return (
    <div className="flex h-full w-full">
      <div className="flex-1 relative">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={dbtNodeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeClick={handleNodeClick}
          onPaneClick={handlePaneClick}
          fitView={true}
          fitViewOptions={{ padding: 0.15 }}
          minZoom={0.1}
          maxZoom={2}
          zoomOnDoubleClick={false}
          nodesConnectable={false}
          nodesDraggable={true}
          proOptions={{ hideAttribution: true }}
        >
          <Background
            color="#27272a"
            variant={BackgroundVariant.Dots}
            gap={20}
            size={1}
          />
          <Controls
            position="bottom-right"
            showInteractive={false}
            className="!bg-zinc-900 !border-zinc-700 !shadow-lg [&>button]:!bg-zinc-800 [&>button]:!border-zinc-700 [&>button]:!text-zinc-300 [&>button:hover]:!bg-zinc-700"
          />
        </ReactFlow>
      </div>

      {selectedNode && (
        <ModelDetailPanel
          node={selectedNode}
          data={data}
          onClose={() => onSelectNode(null)}
          onNavigate={handleNavigateToNode}
        />
      )}
    </div>
  );
};
