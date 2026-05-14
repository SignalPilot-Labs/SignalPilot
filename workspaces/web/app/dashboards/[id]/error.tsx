"use client";

import { PageHeader } from "@/components/ui/PageHeader";
import { TerminalBar } from "@/components/ui/PageHeader";
import { PRIMARY_BTN_CLASS } from "@/components/ui/button-classes";

interface ErrorPageProps {
  error: Error & { digest?: string };
  reset: () => void;
}

export default function DashboardError({ error, reset }: ErrorPageProps) {
  const isDev = process.env.NODE_ENV === "development";

  return (
    <div className="p-8 max-w-[1400px] animate-fade-in">
      <PageHeader title="dashboard" subtitle="error" description="Failed to load this dashboard." />
      <TerminalBar path="dashboards/…" />
      <div className="max-w-md bg-[var(--color-bg-card)] border border-[var(--color-border)] p-6">
        <h2 className="text-lg font-semibold text-[var(--color-text)] mb-2">
          Failed to load dashboard
        </h2>
        {isDev && (
          <pre className="text-sm text-[var(--color-text-dim)] bg-[var(--color-bg)] border border-[var(--color-border)] p-3 overflow-auto mb-4 whitespace-pre-wrap">
            {error.message}
          </pre>
        )}
        {error.digest && (
          <p className="text-xs text-[var(--color-text-dim)] mb-4">
            Error ID: <code>{error.digest}</code>
          </p>
        )}
        <button
          onClick={reset}
          className={`${PRIMARY_BTN_CLASS} w-full`}
        >
          Try again
        </button>
      </div>
    </div>
  );
}
