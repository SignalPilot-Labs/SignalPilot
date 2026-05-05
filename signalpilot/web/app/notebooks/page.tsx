"use client";

import { PageHeader, TerminalBar } from "@/components/ui/page-header";
import { NotebookList } from "@/components/notebooks/notebook-list";
import { useNotebooks } from "@/lib/hooks/use-gateway-data";
import { Skeleton } from "@/components/ui/skeleton";

export default function NotebooksPage() {
  const { data: notebooks, isLoading, error } = useNotebooks();

  return (
    <div className="p-8 max-w-[1400px] animate-fade-in">
      <PageHeader
        title="notebooks"
        subtitle="jupyter"
        description="Upload and analyze Jupyter notebooks. View cells, outputs, and analysis results."
      />
      <TerminalBar path="notebooks --list" />

      {isLoading && (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-36" />
          ))}
        </div>
      )}

      {error && (
        <div className="border border-[var(--color-error)]/30 bg-[var(--color-bg-card)] p-6">
          <p className="text-[12px] text-[var(--color-error)] tracking-wider">
            failed to load notebooks: {error instanceof Error ? error.message : "unknown error"}
          </p>
        </div>
      )}

      {!isLoading && !error && (
        <NotebookList notebooks={notebooks ?? []} />
      )}
    </div>
  );
}
