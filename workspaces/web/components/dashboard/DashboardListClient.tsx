"use client";

import { useState } from "react";
import Link from "next/link";
import type { DashboardDefinition } from "@/lib/dashboards/types";
import { NewDashboardModal } from "./NewDashboardModal";
import { TimeAgo } from "@/components/ui/TimeAgo";

interface DashboardListClientProps {
  dashboards: DashboardDefinition[];
}

export function DashboardListClient({ dashboards }: DashboardListClientProps) {
  const [modalOpen, setModalOpen] = useState(false);

  return (
    <>
      <div className="flex items-center justify-between mb-6">
        <p className="text-sm text-[var(--color-text-muted)]">
          {dashboards.length} dashboard{dashboards.length !== 1 ? "s" : ""}
        </p>
        <button
          onClick={() => setModalOpen(true)}
          className="px-4 py-2 text-[12px] uppercase tracking-wider bg-[var(--color-text)] text-[var(--color-bg)] hover:opacity-90 transition-opacity"
        >
          + new dashboard
        </button>
      </div>

      {dashboards.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 px-8 text-center border border-[var(--color-border)] bg-[var(--color-bg-card)]">
          <h2 className="text-base font-light tracking-wide text-[var(--color-text)] mb-2">
            no dashboards yet
          </h2>
          <p className="text-sm text-[var(--color-text-muted)] max-w-sm">
            Create one manually or run an agent to build dashboards automatically.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {dashboards.map((d) => (
            <Link
              key={d.id}
              href={`/dashboards/${d.id}`}
              className="block bg-[var(--color-sidebar)] border border-[var(--color-border)] p-4 hover:border-[var(--color-border-hover)] transition-colors group"
            >
              <h3 className="text-[13px] font-bold tracking-wider uppercase text-[var(--color-text)] group-hover:text-[var(--color-text)] mb-1">
                {d.name}
              </h3>
              {d.description && (
                <p className="text-[12px] text-[var(--color-text-muted)] mb-3 line-clamp-2">
                  {d.description}
                </p>
              )}
              <div className="flex items-center gap-3 text-[11px] text-[var(--color-text-dim)]">
                <span>{d.charts.length} chart{d.charts.length !== 1 ? "s" : ""}</span>
                <span>&middot;</span>
                <TimeAgo timestamp={d.updatedAt} />
              </div>
            </Link>
          ))}
        </div>
      )}

      <NewDashboardModal open={modalOpen} onClose={() => setModalOpen(false)} />
    </>
  );
}
