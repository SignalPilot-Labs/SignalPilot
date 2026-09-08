"use client";

// The datasets stored with one dashboard version: name, file, rows, size,
// and a Download that pulls the exact bytes the version was built from.

import { ArrowDownToLine } from "lucide-react";
import { useState } from "react";

import type { DashboardVersion } from "~/lib/api/dashboards";
import { formatByteSize } from "~/lib/chat-artifacts";

export type DownloadDataset = (version: DashboardVersion, name: string) => Promise<void>;

export function DashboardVersionDatasets({
  version,
  onDownload,
}: {
  version: DashboardVersion;
  onDownload: DownloadDataset;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const entries = Object.entries(version.dataset_meta);

  const download = async (name: string) => {
    setBusy(name);
    try {
      await onDownload(version, name);
    } finally {
      setBusy(null);
    }
  };

  if (entries.length === 0) {
    return (
      <p
        data-testid="dashboard-version-datasets"
        className="px-4 pb-3 pl-16 text-[11.5px] text-[var(--color-text-dim)]"
      >
        No stored dataset files; every dataset is inline in the spec.
      </p>
    );
  }

  return (
    <ul data-testid="dashboard-version-datasets" className="space-y-1 px-4 pb-3 pl-16">
      {entries.map(([name, meta]) => (
        <li
          key={name}
          data-testid="dashboard-version-dataset"
          data-dataset={name}
          className="flex items-center gap-3 text-[11.5px]"
        >
          <span className="min-w-0 flex-1 truncate">
            <span className="font-mono text-[var(--color-text)]">{name}</span>
            <span className="text-[var(--color-text-dim)]">
              {" "}· {meta.filename} · {meta.row_count.toLocaleString("en-US")}{" "}
              {meta.row_count === 1 ? "row" : "rows"} · {formatByteSize(meta.byte_size)}
            </span>
          </span>
          <button
            type="button"
            data-testid="dashboard-version-dataset-download"
            aria-label={`Download ${meta.filename}`}
            disabled={busy !== null}
            onClick={() => void download(name)}
            className="inline-flex h-6 items-center gap-1 rounded-md border border-[var(--color-border)] px-2 text-[11px] text-[var(--color-text-muted)] transition-colors hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)] disabled:cursor-not-allowed disabled:opacity-50"
          >
            <ArrowDownToLine className={`h-3 w-3 ${busy === name ? "animate-pulse" : ""}`} strokeWidth={1.5} />
            Download
          </button>
        </li>
      ))}
    </ul>
  );
}
