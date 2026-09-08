"use client";

// Version history: every immutable version newest first, the live one
// marked, a Restore action that creates a new version from an old one, and
// a per-version expand listing the stored dataset files for download.

import { ChevronRight, History, RotateCcw } from "lucide-react";
import { useState } from "react";

import type { DashboardVersion } from "~/lib/api/dashboards";
import { relativeTime } from "~/lib/dashboards/format";

import { BUTTON_CLASS, CurrentChip, versionOriginLabel } from "./dashboard-chips";
import { DashboardVersionDatasets, type DownloadDataset } from "./dashboard-version-datasets";

export function DashboardVersionList({
  versions,
  currentVersionId,
  canEdit,
  now = () => Date.now(),
  onRestore,
  onDownloadDataset,
}: {
  versions: DashboardVersion[];
  currentVersionId: string | null;
  canEdit: boolean;
  now?: () => number;
  onRestore: (version: DashboardVersion) => Promise<void>;
  onDownloadDataset: DownloadDataset;
}) {
  const [busyId, setBusyId] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const restore = async (version: DashboardVersion) => {
    setBusyId(version.id);
    try {
      await onRestore(version);
    } finally {
      setBusyId(null);
    }
  };

  return (
    <section
      data-testid="dashboard-version-list"
      aria-labelledby="dashboard-versions-title"
      className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-card)]"
    >
      <header className="flex items-center gap-2 border-b border-[var(--color-border)] px-4 py-3">
        <History className="h-3.5 w-3.5 text-[var(--color-text-dim)]" strokeWidth={1.5} />
        <h2 id="dashboard-versions-title" className="text-[12.5px] font-medium text-[var(--color-text)]">
          Versions
        </h2>
        <span className="text-[11.5px] text-[var(--color-text-dim)]">{versions.length}</span>
      </header>
      {versions.length === 0 ? (
        <p className="px-4 py-6 text-center text-[12px] text-[var(--color-text-dim)]">No versions yet.</p>
      ) : (
        <ol className="divide-y divide-[var(--color-border)]">
          {versions.map((version) => {
            const isCurrent = version.id === currentVersionId;
            const expanded = expandedId === version.id;
            const datasetCount = Object.keys(version.dataset_meta).length;
            return (
              <li
                key={version.id}
                data-testid="dashboard-version-row"
                data-version-no={version.version_no}
                data-current={isCurrent ? "1" : "0"}
                data-expanded={expanded ? "1" : "0"}
              >
                <div className="flex items-center gap-3 px-4 py-2.5">
                  <button
                    type="button"
                    data-testid="dashboard-version-toggle"
                    aria-expanded={expanded}
                    aria-label={`${expanded ? "Hide" : "Show"} datasets of version ${version.version_no}`}
                    onClick={() => setExpandedId(expanded ? null : version.id)}
                    className="-ml-1 flex h-6 w-6 flex-none items-center justify-center rounded-md text-[var(--color-text-dim)] transition-colors hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
                  >
                    <ChevronRight
                      className={`h-3.5 w-3.5 transition-transform ${expanded ? "rotate-90" : ""}`}
                      strokeWidth={1.75}
                    />
                  </button>
                  <span className="w-7 flex-none font-mono text-[12px] text-[var(--color-text)]">
                    v{version.version_no}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[12.5px] text-[var(--color-text)]">
                      {versionOriginLabel(version.produced_by)}
                      {isCurrent && (
                        <span className="ml-2 inline-block align-middle">
                          <CurrentChip />
                        </span>
                      )}
                    </p>
                    <p className="text-[11.5px] text-[var(--color-text-dim)]">
                      {relativeTime(version.created_at, now())} · {version.chart_count}{" "}
                      {version.chart_count === 1 ? "chart" : "charts"} · {datasetCount}{" "}
                      {datasetCount === 1 ? "dataset file" : "dataset files"}
                    </p>
                  </div>
                  {canEdit && !isCurrent && (
                    <button
                      type="button"
                      data-testid="dashboard-version-restore"
                      disabled={busyId !== null}
                      onClick={() => void restore(version)}
                      className={BUTTON_CLASS}
                    >
                      <RotateCcw className={`h-3 w-3 ${busyId === version.id ? "animate-spin" : ""}`} strokeWidth={1.5} />
                      Restore
                    </button>
                  )}
                </div>
                {expanded && <DashboardVersionDatasets version={version} onDownload={onDownloadDataset} />}
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
