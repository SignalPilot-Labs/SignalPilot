import type { StandaloneChatEvent } from "~/lib/api";

/** Display only diagnostic fields explicitly published by the gateway. */
export function ChatErrorDetails({ events, runId }: { events: StandaloneChatEvent[]; runId: string }) {
  const payload = [...events].reverse().find((event) => event.run_id === runId && event.type === "error" &&
    (typeof event.payload.raw_error === "string" || typeof event.payload.stderr === "string" ||
      event.payload.raw_error_truncated === true || event.payload.stderr_truncated === true))?.payload;
  if (!payload) return null;
  const rawError = typeof payload.raw_error === "string" ? payload.raw_error : "";
  const stderr = typeof payload.stderr === "string" ? payload.stderr : "";
  const rawTruncated = payload.raw_error_truncated === true;
  const stderrTruncated = payload.stderr_truncated === true;
  if (!rawError && !stderr && !rawTruncated && !stderrTruncated) return null;
  return <details className="my-3 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)] p-4">
    <summary className="cursor-pointer text-sm font-medium">Error details</summary>
    <p className="mt-2 text-xs text-[var(--color-text-dim)]">Original error output with secrets redacted.</p>
    {(rawError || rawTruncated) && <div className="mt-4">
      <h3 className="text-xs font-medium">Original error</h3>
      <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-[var(--color-bg)] p-3 text-xs">{rawError || "No error text retained."}</pre>
      {rawTruncated && <p className="mt-1 text-xs text-[var(--color-warning)]">Original error was truncated; only part of the output is shown.</p>}
    </div>}
    {(stderr || stderrTruncated) && <div className="mt-4">
      <h3 className="text-xs font-medium">Standard error (stderr)</h3>
      <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-[var(--color-bg)] p-3 text-xs">{stderr || "No standard error text retained."}</pre>
      {stderrTruncated && <p className="mt-1 text-xs text-[var(--color-warning)]">Standard error was truncated; only part of the output is shown.</p>}
    </div>}
  </details>;
}
