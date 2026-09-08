"use client";

// Read-only public view at /dashboards/shared/[token]: the renderer with
// live filters and a quiet caption, no app chrome and no actions.

import { AlertTriangle } from "lucide-react";
import { useEffect, useState } from "react";

import type { DashboardBundle } from "~/lib/api/dashboards";
import { requestErrorStatus } from "~/lib/api/client";
import { relativeTime } from "~/lib/dashboards/format";
import { DashboardRenderer, type FilterState } from "~/dashboard-renderer";

import { useDashboardsApi, useDashboardsClock } from "./dashboards-api-context";

type State =
  | { phase: "loading" }
  | { phase: "error"; notFound: boolean }
  | { phase: "ready"; bundle: DashboardBundle };

export function DashboardSharedView({ token }: { token: string }) {
  const api = useDashboardsApi();
  const now = useDashboardsClock();
  const [state, setState] = useState<State>({ phase: "loading" });
  const [filterState, setFilterState] = useState<FilterState>({});

  useEffect(() => {
    let active = true;
    setState({ phase: "loading" });
    api
      .getSharedDashboard(token)
      .then((bundle) => {
        if (active) setState({ phase: "ready", bundle });
      })
      .catch((error: unknown) => {
        if (active) setState({ phase: "error", notFound: requestErrorStatus(error) === 404 });
      });
    return () => {
      active = false;
    };
  }, [api, token]);

  return (
    <div data-testid="dashboard-shared" className="min-h-screen bg-[var(--color-bg)] p-4 md:p-8">
      <div className="mx-auto max-w-7xl">
        {state.phase === "loading" && (
          <div
            aria-busy="true"
            className="h-[480px] animate-pulse rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-card)]"
          />
        )}
        {state.phase === "error" && (
          <div
            role="alert"
            className="flex min-h-[320px] flex-col items-center justify-center rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-card)] px-6 text-center"
          >
            <AlertTriangle className="h-5 w-5 text-[var(--color-text-dim)]" />
            <p className="mt-3 text-[14px] text-[var(--color-text)]">
              {state.notFound ? "This shared dashboard is not available." : "Could not load this dashboard."}
            </p>
            <p className="mt-1 text-[12.5px] text-[var(--color-text-dim)]">
              {state.notFound
                ? "The link may have been revoked, or the dashboard archived."
                : "Try again in a moment."}
            </p>
          </div>
        )}
        {state.phase === "ready" && (
          <>
            <div className="overflow-hidden rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-card)]">
              <DashboardRenderer
                spec={state.bundle.spec}
                datasets={state.bundle.datasets}
                theme="dark"
                filterState={filterState}
                onFilterStateChange={setFilterState}
              />
            </div>
            <p className="mt-3 text-[11.5px] text-[var(--color-text-dim)]">
              Version {state.bundle.version.version_no} · updated{" "}
              {relativeTime(state.bundle.version.created_at, now())} · shared from SignalPilot
            </p>
          </>
        )}
      </div>
    </div>
  );
}
