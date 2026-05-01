import type { ChartDefinitionV1 } from "@/lib/charts/types";
import type { ChartResponse, ChartRunResponse } from "@/lib/api/types";
import { buildSamplePreview } from "@/lib/charts/preview-sample";
import { EChart } from "@/components/charts/EChart";
import { DataTable } from "@/components/charts/DataTable";
import { NumberKpi } from "@/components/charts/NumberKpi";

interface ChartPreviewProps {
  definition: ChartDefinitionV1;
}

export function ChartPreview({ definition }: ChartPreviewProps) {
  const preview = buildSamplePreview(definition);

  return (
    <section className="rounded-card border border-border bg-surface p-6 shadow-card">
      <h2 className="text-base font-semibold text-fg mb-3">Preview</h2>

      {preview.kind === "echart" && (
        <EChart option={preview.option} ariaLabel={preview.ariaLabel} height={320} />
      )}

      {preview.kind === "table" && (() => {
        const run: ChartRunResponse = {
          chart_id: definition.id,
          cache_key: "",
          cached: false,
          computed_at: definition.createdAt,
          columns: preview.columns,
          rows: preview.rows,
          truncated: false,
        };
        return <DataTable run={run} caption={preview.caption} />;
      })()}

      {preview.kind === "kpi" && (() => {
        const chart: ChartResponse = {
          id: definition.id,
          workspace_id: "sample",
          title: definition.name,
          chart_type: "number",
          echarts_option_json: {},
          created_at: definition.createdAt,
          updated_at: definition.createdAt,
          created_by: null,
          query: null,
        };
        const run: ChartRunResponse = {
          chart_id: definition.id,
          cache_key: "",
          cached: false,
          computed_at: definition.createdAt,
          columns: [{ name: "total", type: "integer" }],
          rows: [[preview.value]],
          truncated: false,
        };
        return <NumberKpi chart={chart} run={run} />;
      })()}

      <p className="text-xs text-muted mt-3">Sample data — query execution not yet wired</p>
    </section>
  );
}
