import type { ChartDefinitionV1 } from "@/lib/charts/types";

interface ChartDetailProps {
  definition: ChartDefinitionV1;
}

export function ChartDetail({ definition }: ChartDetailProps) {
  return (
    <div className="rounded-card border border-border bg-surface p-6 shadow-card">
      <h1 className="text-2xl font-semibold text-fg mb-2">{definition.name}</h1>

      <dl className="mb-4 flex flex-col gap-1 text-sm">
        <div className="flex gap-2">
          <dt className="text-muted">Type</dt>
          <dd className="text-fg">{definition.type}</dd>
        </div>
        <div className="flex gap-2">
          <dt className="text-muted">Created</dt>
          <dd className="text-fg">{new Date(definition.createdAt).toLocaleString()}</dd>
        </div>
      </dl>

      <section>
        <h2 className="text-base font-semibold text-fg mb-2">SQL</h2>
        <pre className="rounded-control bg-bg p-3 overflow-auto">
          <code className="font-mono text-sm text-fg">{definition.sql}</code>
        </pre>
      </section>
    </div>
  );
}
