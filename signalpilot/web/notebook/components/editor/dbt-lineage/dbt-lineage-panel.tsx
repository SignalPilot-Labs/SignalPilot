import { DatabaseIcon, GitBranchIcon, Loader2Icon } from "lucide-react";
import React from "react";
import { ReactFlowProvider } from "reactflow";
import "reactflow/dist/style.css";
import { PanelEmptyState } from "../chrome/panels/empty-state";
import { LineageGraph } from "./lineage-graph";
import { LineageToolbar } from "./lineage-toolbar";
import {
  useDbtLineage,
  useLayoutDirection,
  useLineageFilter,
  useSelectedNode,
} from "./use-dbt-lineage";

const DbtLineagePanel: React.FC = () => {
  const { data, loading, error, reload } = useDbtLineage();
  const [selectedNode, setSelectedNode] = useSelectedNode();
  const [layoutDirection, setLayoutDirection] = useLayoutDirection();
  const { filter, toggleLayer, setSearch } = useLineageFilter();

  if (loading && !data) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center gap-3">
          <Loader2Icon className="w-6 h-6 animate-spin text-zinc-500" />
          <span className="text-xs text-zinc-500">Loading lineage...</span>
        </div>
      </div>
    );
  }

  if (error && !data) {
    return (
      <PanelEmptyState
        title="No lineage data"
        description={error}
        icon={<DatabaseIcon />}
      />
    );
  }

  if (!data || data.nodes.size === 0) {
    return (
      <PanelEmptyState
        title="No dbt models"
        description="Connect a dbt project and run 'dbt parse' to see the lineage graph."
        icon={<GitBranchIcon />}
      />
    );
  }

  const visibleNodes = [...data.nodes.values()].filter(
    (n) =>
      filter.layers.has(n.layer) &&
      (!filter.searchQuery ||
        n.name.toLowerCase().includes(filter.searchQuery.toLowerCase())),
  );

  const visibleEdges = data.edges.filter(
    (e) =>
      visibleNodes.some((n) => n.id === e.source) &&
      visibleNodes.some((n) => n.id === e.target),
  );

  return (
    <div className="flex flex-col h-full overflow-hidden bg-zinc-950">
      <LineageToolbar
        filter={filter}
        onToggleLayer={toggleLayer}
        onSetSearch={setSearch}
        layoutDirection={layoutDirection}
        onSetDirection={setLayoutDirection}
        onReload={reload}
        loading={loading}
        nodeCount={visibleNodes.length}
        edgeCount={visibleEdges.length}
      />
      <div className="flex-1 overflow-hidden">
        <ReactFlowProvider>
          <LineageGraph
            data={data}
            layoutDirection={layoutDirection}
            filter={filter}
            selectedNode={selectedNode}
            onSelectNode={setSelectedNode}
          />
        </ReactFlowProvider>
      </div>
    </div>
  );
};

export default DbtLineagePanel;
