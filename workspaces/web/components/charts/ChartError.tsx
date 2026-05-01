interface ChartErrorProps {
  code?: string;
  message?: string;
}

export function ChartError({ code, message }: ChartErrorProps) {
  return (
    <div
      role="alert"
      className="flex items-start gap-2 rounded-control border border-danger-border bg-danger-bg px-3 py-2 text-sm"
    >
      <span className="shrink-0 text-danger-fg font-medium">Error</span>
      {code && (
        <code className="shrink-0 rounded bg-danger-code-bg px-1 py-0.5 text-xs text-danger-code-fg font-mono">
          {code}
        </code>
      )}
      <span className="text-danger">
        {message ?? "An error occurred while loading this chart."}
      </span>
    </div>
  );
}
