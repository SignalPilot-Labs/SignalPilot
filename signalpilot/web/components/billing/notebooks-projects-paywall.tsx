"use client";

import { Code } from "lucide-react";

export function NotebooksProjectsPaywall() {
  return (
    <div className="p-8 animate-fade-in">
      <div className="max-w-md mx-auto mt-24">
        <div className="flex items-center gap-3 mb-6">
          <Code className="w-6 h-6 text-[var(--color-text)]" />
          <h1 className="text-lg font-bold uppercase tracking-wider text-[var(--color-text)]">
            SignalPilot IDE
          </h1>
        </div>
        <div className="border border-[var(--color-border)] p-6 space-y-4">
          <p className="text-sm text-[var(--color-text)]">
            Notebooks &amp; projects are a Pro feature.
          </p>
          <p className="text-xs text-[var(--color-text-dim)] leading-relaxed">
            Upgrade to Pro, Team, or Enterprise to create governed notebook
            workspaces backed by your connections and dbt projects.
          </p>
          <a
            href="/settings/billing"
            className="inline-flex items-center gap-2 px-5 py-3 bg-[var(--color-text)] text-[var(--color-bg)] text-xs font-medium tracking-wider uppercase transition-all hover:opacity-90"
          >
            Upgrade plan
          </a>
        </div>
      </div>
    </div>
  );
}
