import type { ChartDefinitionV1 } from "@/lib/charts/types";
import { ChartPreview } from "@/components/charts/preview/ChartPreview";

interface ChartDetailProps {
  definition: ChartDefinitionV1;
}

export function ChartDetail({ definition }: ChartDetailProps) {
  return (
    <div className="flex flex-col gap-6">
      <div className="bg-[var(--color-bg-card)] border border-[var(--color-border)] p-6">
        <h1 className="text-2xl font-semibold text-[var(--color-text)] mb-2">{definition.name}</h1>

        <dl className="mb-4 flex flex-col gap-1 text-sm">
          <div className="flex gap-2">
            <dt className="text-[var(--color-text-muted)] uppercase tracking-[0.15em] text-[10px]">Type</dt>
            <dd className="text-[var(--color-text)]">{definition.type}</dd>
          </div>
          <div className="flex gap-2">
            <dt className="text-[var(--color-text-muted)] uppercase tracking-[0.15em] text-[10px]">Created</dt>
            <dd className="text-[var(--color-text-dim)]">{new Date(definition.createdAt).toLocaleString()}</dd>
          </div>
        </dl>

        <section>
          <h2 className="text-base font-semibold text-[var(--color-text)] mb-2">SQL</h2>
          <pre className="bg-[var(--color-bg)] border border-[var(--color-border)] p-3 overflow-auto">
            <code className="font-mono text-sm text-[var(--color-text)]">{definition.sql}</code>
          </pre>
        </section>
      </div>

      <ChartPreview definition={definition} />
    </div>
  );
}
