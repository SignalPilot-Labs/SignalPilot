"use client";

import { useState } from "react";
import Link from "next/link";
import type { DashboardDefinition } from "@/lib/dashboards/types";
import { NewDashboardModal } from "./new-dashboard-modal";
import { TimeAgo } from "@/components/ui/time-ago";
import { EmptyTerminal, EmptyState } from "@/components/ui/empty-states";

export function DashboardListClient({ dashboards }: { dashboards: DashboardDefinition[] }) {
  const [modalOpen, setModalOpen] = useState(false);

  return (
    <>
      <div className="flex items-center justify-between mb-6">
        <p className="text-[12px] text-[var(--color-text-muted)] tracking-wider">
          {dashboards.length} dashboard{dashboards.length !== 1 ? "s" : ""}
        </p>
        <button
          onClick={() => setModalOpen(true)}
          className="px-4 py-2 text-[12px] uppercase tracking-[0.15em] bg-[var(--color-text)] text-[var(--color-bg)] hover:opacity-90 transition-opacity"
        >
          + new dashboard
        </button>
      </div>

      {dashboards.length === 0 ? (
        <EmptyState
          icon={EmptyTerminal}
          title="no dashboards yet"
          description="Create one manually or use the MCP tools to build dashboards with an agent."
        />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {dashboards.map((d) => (
            <Link
              key={d.id}
              href={`/dashboards/${d.id}`}
              className="block bg-[var(--color-bg-card)] border border-[var(--color-border)] p-5 hover:bg-[var(--color-bg-hover)] transition-all card-glow card-accent-top group"
            >
              <h3 className="text-[12px] font-medium tracking-[0.15em] uppercase text-[var(--color-text)] group-hover:text-[var(--color-text)] mb-1">
                {d.name}
              </h3>
              {d.description && (
                <p className="text-[12px] text-[var(--color-text-muted)] mb-3 line-clamp-2">
                  {d.description}
                </p>
              )}
              <div className="flex items-center gap-3 text-[11px] text-[var(--color-text-dim)] tracking-wider">
                <span>{d.charts.length} chart{d.charts.length !== 1 ? "s" : ""}</span>
                <span>&middot;</span>
                <TimeAgo timestamp={new Date(d.updatedAt).getTime() / 1000} />
              </div>
            </Link>
          ))}
        </div>
      )}

      <NewDashboardModal open={modalOpen} onClose={() => setModalOpen(false)} />
    </>
  );
}
