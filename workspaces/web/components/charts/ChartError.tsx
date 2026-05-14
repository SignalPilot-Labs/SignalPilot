interface ChartErrorProps {
  code?: string;
  message?: string;
}

export function ChartError({ code, message }: ChartErrorProps) {
  return (
    <div
      role="alert"
      className="flex items-start gap-2 border px-2 py-0.5 text-[10px] uppercase tracking-[0.15em] badge-error"
    >
      <span className="shrink-0 font-medium">Error</span>
      {code && (
        <code className="shrink-0 bg-[var(--color-bg-card)] text-[var(--color-error)] border border-[var(--color-error)] font-mono text-xs p-3">
          {code}
        </code>
      )}
      <span>
        {message ?? "An error occurred while loading this chart."}
      </span>
    </div>
  );
}
