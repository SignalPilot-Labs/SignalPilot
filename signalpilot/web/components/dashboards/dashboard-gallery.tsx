"use client";

// The team gallery at /dashboards: every dashboard the viewer can open,
// newest updated first, with an archived toggle and a publish hint.

import { AlertTriangle, Archive, LayoutGrid, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import type { PublishedDashboard } from "~/lib/api/dashboards";
import { userFacingErrorMessage } from "~/lib/api/client";
import { PageHeader } from "~/components/ui/page-header";

import { DashboardCard } from "./dashboard-card";
import { BUTTON_CLASS } from "./dashboard-chips";
import { useDashboardsApi } from "./dashboards-api-context";

type LoadState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; dashboards: PublishedDashboard[] };

function PublishHint() {
  return (
    <p
      data-testid="dashboard-publish-hint"
      className="rounded-xl border border-dashed border-[var(--color-border)] px-4 py-3 text-[12.5px] leading-5 text-[var(--color-text-muted)]"
    >
      <span className="font-medium text-[var(--color-text)]">How to publish:</span> ask the chat
      for a dashboard, open it in the artifacts panel, then choose{" "}
      <span className="rounded border border-[var(--color-border)] px-1 py-px text-[11px] text-[var(--color-text)]">
        Publish
      </span>
      . Published dashboards live here, independent of the chat, and can refresh on a schedule.
    </p>
  );
}

function EmptyState({ archivedShown }: { archivedShown: boolean }) {
  return (
    <div
      data-testid="dashboard-gallery-empty"
      className="flex flex-col items-center rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-card)] px-6 py-14 text-center"
    >
      <LayoutGrid className="h-6 w-6 text-[var(--color-text-dim)]" strokeWidth={1.25} />
      <p className="mt-4 text-[14px] font-medium text-[var(--color-text)]">
        {archivedShown ? "No dashboards yet" : "No active dashboards"}
      </p>
      <p className="mt-1.5 max-w-md text-[12.5px] leading-5 text-[var(--color-text-muted)]">
        Dashboards start in a chat. Ask for one, review it in the artifacts panel, and publish
        it to share with the team and keep it fresh on a schedule.
      </p>
    </div>
  );
}

export function DashboardGallery() {
  const api = useDashboardsApi();
  const [includeArchived, setIncludeArchived] = useState(false);
  const [state, setState] = useState<LoadState>({ phase: "loading" });
  const [reloadKey, setReloadKey] = useState(0);

  const load = useCallback(async () => {
    try {
      const { dashboards } = await api.listDashboards({ includeArchived });
      return { phase: "ready", dashboards } as const;
    } catch (error) {
      const fallback = "Could not load dashboards.";
      return { phase: "error", message: userFacingErrorMessage(error, fallback) ?? fallback } as const;
    }
  }, [api, includeArchived]);

  useEffect(() => {
    let active = true;
    setState((prev) => (prev.phase === "ready" ? prev : { phase: "loading" }));
    void load().then((next) => {
      if (active) setState(next);
    });
    return () => {
      active = false;
    };
  }, [load, reloadKey]);

  const dashboards = state.phase === "ready" ? state.dashboards : [];
  const activeCount = dashboards.filter((d) => !d.archived_at).length;
  const subtitle = state.phase === "ready" ? `${dashboards.length}` : "…";

  return (
    <div data-testid="dashboard-gallery" className="min-h-screen p-5 md:p-8">
      <div className="mx-auto max-w-7xl">
        <PageHeader
          title="Dashboards"
          subtitle={subtitle}
          description="Published dashboards shared with the team, refreshed on a schedule."
          actions={
            <>
              <button
                type="button"
                data-testid="dashboard-gallery-archived-toggle"
                aria-pressed={includeArchived}
                onClick={() => setIncludeArchived((value) => !value)}
                className={`${BUTTON_CLASS} ${includeArchived ? "border-[var(--color-border-active)] text-[var(--color-text)]" : ""}`}
              >
                <Archive className="h-3.5 w-3.5" strokeWidth={1.5} />
                {includeArchived ? "Hide archived" : "Show archived"}
              </button>
              <button
                type="button"
                aria-label="Reload dashboards"
                onClick={() => setReloadKey((value) => value + 1)}
                className={BUTTON_CLASS}
              >
                <RefreshCw
                  className={`h-3.5 w-3.5 ${state.phase === "loading" ? "animate-spin" : ""}`}
                  strokeWidth={1.5}
                />
                Reload
              </button>
            </>
          }
        />
        <div className="mb-6">
          <PublishHint />
        </div>
        {state.phase === "error" && (
          <div
            role="alert"
            className="mb-6 flex items-center gap-2 rounded-xl border border-[var(--color-error)]/30 bg-[var(--color-error)]/5 px-4 py-3 text-[12.5px] text-[var(--color-error)]"
          >
            <AlertTriangle className="h-4 w-4 flex-none" />
            {state.message}
          </div>
        )}
        {state.phase === "loading" && (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3" aria-busy="true">
            {[0, 1, 2].map((index) => (
              <div
                key={index}
                className="h-[172px] animate-pulse rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-card)]"
              />
            ))}
          </div>
        )}
        {state.phase === "ready" && dashboards.length === 0 && (
          <EmptyState archivedShown={includeArchived} />
        )}
        {state.phase === "ready" && dashboards.length > 0 && (
          <>
            <p className="mb-3 text-[11.5px] uppercase tracking-[0.08em] text-[var(--color-text-dim)]">
              {activeCount} active
              {includeArchived && dashboards.length - activeCount > 0
                ? ` · ${dashboards.length - activeCount} archived`
                : ""}
            </p>
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {dashboards.map((dashboard) => (
                <DashboardCard key={dashboard.id} dashboard={dashboard} />
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
