"use client";

import { GitBranch } from "lucide-react";

import type { DbtMapInfo } from "~/lib/types";
import { DbtMapStatusLine } from "~/components/projects/dbt-map-status";

function Toggle({ on, children }: { on: boolean; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2.5 text-xs text-[var(--color-text)]">
      <span
        className={`rounded px-1.5 py-0.5 font-mono text-[10px] ${
          on
            ? "bg-[var(--color-success)]/10 text-[var(--color-success)]"
            : "bg-[var(--color-bg-input)] text-[var(--color-text-dim)]"
        }`}
      >
        {on ? "on" : "off"}
      </span>
      {children}
    </div>
  );
}

/**
 * The member view of a project's dbt / automation settings: every value the
 * admin form edits, rendered as text. No inputs, no compile, no save.
 */
export function ProjectAutomationReadOnly({
  dbtDir,
  detectedDir,
  watchedBranches,
  autoCompileOnPush,
  compileOnPr,
  prAgentTrigger,
  mapStatus,
  mapInfo,
}: {
  /** Explicit folder, or null for auto-detect. */
  dbtDir: string | null;
  detectedDir: string | undefined;
  watchedBranches: string[];
  autoCompileOnPush: boolean;
  compileOnPr: boolean;
  prAgentTrigger: boolean;
  mapStatus: string;
  mapInfo: DbtMapInfo | null;
}) {
  const folder =
    dbtDir === null
      ? `Auto-detect${detectedDir !== undefined ? ` (${detectedDir === "" ? "repo root" : detectedDir})` : ""}`
      : dbtDir === ""
        ? "repo root"
        : dbtDir;
  return (
    <div className="space-y-5 p-6" data-testid="project-automation-readonly">
      <div>
        <span className="mb-1.5 block text-xs text-[var(--color-text-dim)]">dbt project folder</span>
        <p className="text-sm text-[var(--color-text)]">{folder}</p>
      </div>

      <div>
        <span className="mb-1.5 block text-xs text-[var(--color-text-dim)]">Watched branches</span>
        {watchedBranches.length === 0 ? (
          <p className="text-sm text-[var(--color-text-dim)]">none</p>
        ) : (
          <div className="flex flex-wrap items-center gap-1.5">
            {watchedBranches.map((branch) => (
              <span
                key={branch}
                className="inline-flex items-center gap-1 rounded-[8px] border border-[var(--color-border)] bg-[var(--color-bg-input)] px-2 py-1 text-[11px] text-[var(--color-text)]"
              >
                <GitBranch className="h-3 w-3 text-[var(--color-text-dim)]" />
                {branch}
              </span>
            ))}
          </div>
        )}
      </div>

      <div className="space-y-2.5">
        <Toggle on={autoCompileOnPush}>Recompile the dbt map on pushes to watched branches</Toggle>
        <Toggle on={compileOnPr}>Compile the dbt map for pull request branches</Toggle>
        <Toggle on={prAgentTrigger}>Trigger a SignalPilot agent run on pull requests</Toggle>
      </div>

      <div className="border-t border-[var(--color-border)] pt-4">
        <DbtMapStatusLine status={mapStatus} info={mapInfo} />
      </div>
    </div>
  );
}
