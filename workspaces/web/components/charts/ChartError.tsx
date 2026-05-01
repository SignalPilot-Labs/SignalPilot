interface ChartErrorProps {
  code?: string;
  message?: string;
}

export function ChartError({ code, message }: ChartErrorProps) {
  return (
    <div
      role="alert"
      className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm"
    >
      <span className="shrink-0 text-red-500 font-medium">Error</span>
      {code && (
        <code className="shrink-0 rounded bg-red-100 px-1 py-0.5 text-xs text-red-600 font-mono">
          {code}
        </code>
      )}
      <span className="text-red-700">
        {message ?? "An error occurred while loading this chart."}
      </span>
    </div>
  );
}
