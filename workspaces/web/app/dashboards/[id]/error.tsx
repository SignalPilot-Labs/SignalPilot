"use client";

interface ErrorPageProps {
  error: Error & { digest?: string };
  reset: () => void;
}

export default function DashboardError({ error, reset }: ErrorPageProps) {
  const isDev = process.env.NODE_ENV === "development";

  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-8">
      <div className="max-w-md w-full rounded-card border border-border bg-surface p-6 shadow-card">
        <h2 className="text-lg font-semibold text-fg mb-2">
          Failed to load dashboard
        </h2>
        {isDev && (
          <pre className="text-sm text-muted bg-bg rounded-control p-3 overflow-auto mb-4 whitespace-pre-wrap">
            {error.message}
          </pre>
        )}
        {error.digest && (
          <p className="text-xs text-muted mb-4">
            Error ID: <code>{error.digest}</code>
          </p>
        )}
        <button
          onClick={reset}
          className="rounded-control bg-accent px-4 py-2 text-sm font-medium text-white hover:opacity-90 active:opacity-80 transition-opacity"
        >
          Try again
        </button>
      </div>
    </main>
  );
}
