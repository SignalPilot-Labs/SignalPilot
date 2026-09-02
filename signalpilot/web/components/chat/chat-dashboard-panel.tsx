"use client";

import { ArrowUpRight, Check, LayoutDashboard, Loader2, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import useSWR from "swr";

import { DashboardRuntimeProvider } from "~/components/dashboard/dashboard-runtime-provider";
import type { DashboardAuthoringSession } from "~/components/dashboard/dashboard-authoring-panel";
import type { DashboardQueryReceipt } from "~/lib/dashboard/api-data-source";
import { request } from "~/lib/api";
import { useToast } from "~/components/ui/toast";

import dashboardStyles from "~/components/dashboard/dashboard-runtime.module.css";

type AppliedDashboard = { dashboard: { id: string }; version: { id: string } };

const DASHBOARD_STYLES_READY_PROPERTY = "--dashboard-runtime-styles-ready";

export function ChatDashboardPanel({
  sessionId,
  updateLabel,
  updateRevision = 0,
  queriesEnabled = true,
  onClose,
}: {
  sessionId: string;
  updateLabel?: string | null;
  updateRevision?: number;
  queriesEnabled?: boolean;
  onClose: () => void;
}) {
  const { toast } = useToast();
  const {
    data: session,
    error,
    mutate,
  } = useSWR(
    `dashboard-authoring-session:${sessionId}`,
    () =>
      request<DashboardAuthoringSession>(
        `/api/dashboard-authoring/sessions/${sessionId}`,
      ),
    { revalidateOnFocus: false },
  );
  const [busy, setBusy] = useState(false);
  const [receipts, setReceipts] = useState<
    Record<string, DashboardQueryReceipt>
  >({});
  const [syncingRevision, setSyncingRevision] = useState(false);
  const [runtimeStylesReady, setRuntimeStylesReady] = useState(false);
  const runtimeStyleProbe = useRef<HTMLDivElement>(null);
  const wasUpdating = useRef(false);
  const observedRevision = useRef(0);
  const visibleUpdateLabel =
    updateLabel ??
    (syncingRevision ? "Loading the validated dashboard revision" : null);
  const controlsDisabled = busy || Boolean(visibleUpdateLabel);

  useEffect(() => {
    if (updateLabel) setSyncingRevision(true);
    if (wasUpdating.current && !updateLabel) {
      void mutate().finally(() => setSyncingRevision(false));
    }
    wasUpdating.current = Boolean(updateLabel);
  }, [mutate, updateLabel]);

  useEffect(() => {
    if (!updateRevision || updateRevision <= observedRevision.current) return;
    observedRevision.current = updateRevision;
    void mutate();
  }, [mutate, updateRevision]);

  useEffect(() => {
    setReceipts({});
  }, [session?.draft_revision]);

  useLayoutEffect(() => {
    if (!session || runtimeStylesReady) return;
    const checkStyles = () => {
      const probe = runtimeStyleProbe.current;
      if (
        probe &&
        window
          .getComputedStyle(probe)
          .getPropertyValue(DASHBOARD_STYLES_READY_PROPERTY)
          .trim() === "1"
      ) {
        setRuntimeStylesReady(true);
      }
    };
    checkStyles();
    const interval = window.setInterval(checkStyles, 50);
    return () => window.clearInterval(interval);
  }, [runtimeStylesReady, session]);

  const confirmSql = async (decision: "confirm" | "decline") => {
    if (!session || visibleUpdateLabel) return;
    setBusy(true);
    try {
      await mutate(
        request<DashboardAuthoringSession>(
          `/api/dashboard-authoring/sessions/${session.id}/${decision}-custom-sql`,
          { method: "POST" },
        ),
        { revalidate: false },
      );
    } catch (cause) {
      toast(
        cause instanceof Error ? cause.message : "Could not update the draft",
        "error",
      );
    } finally {
      setBusy(false);
    }
  };

  const apply = async () => {
    if (!session || visibleUpdateLabel) return;
    setBusy(true);
    try {
      const applied = await request<AppliedDashboard>(
        `/api/dashboard-authoring/sessions/${session.id}/apply`,
        {
          method: "POST",
          body: JSON.stringify({
            expected_current_version_id: session.base_version_id,
            visible_complete_result_ids: Object.values(receipts).map(
              (receipt) => receipt.dashboard_result_id,
            ),
          }),
        },
      );
      await mutate();
      toast(`Dashboard saved`, "success");
      window.history.replaceState(
        {},
        "",
        `${window.location.pathname}?dashboard=${encodeURIComponent(session.id)}`,
      );
      void applied;
    } catch (cause) {
      toast(
        cause instanceof Error
          ? cause.message
          : "Could not apply the dashboard",
        "error",
      );
    } finally {
      setBusy(false);
    }
  };

  const discard = async () => {
    if (!session || visibleUpdateLabel) return;
    setBusy(true);
    try {
      await mutate(
        request<DashboardAuthoringSession>(
          `/api/dashboard-authoring/sessions/${session.id}/discard`,
          { method: "POST" },
        ),
        { revalidate: false },
      );
      toast("Dashboard draft discarded", "success");
    } catch (cause) {
      toast(
        cause instanceof Error ? cause.message : "Could not discard the draft",
        "error",
      );
    } finally {
      setBusy(false);
    }
  };

  const retryFailed = async () => {
    if (!session || busy) return;
    setBusy(true);
    try {
      await mutate(
        request<DashboardAuthoringSession>(
          `/api/dashboard-authoring/sessions/${session.id}/retry-failed`,
          { method: "POST" },
        ),
        { revalidate: false },
      );
    } catch (cause) {
      toast(
        cause instanceof Error
          ? cause.message
          : "Could not retry failed charts",
        "error",
      );
    } finally {
      setBusy(false);
    }
  };

  const chartDrafts = session?.chart_drafts ?? [];
  const requiredChartIds = new Set(
    session?.plan?.intents
      .filter((intent) => intent.required !== false)
      .map((intent) => intent.chart_id) ?? [],
  );
  const persistedReadyCount = chartDrafts.filter(
    (draft) =>
      draft.status === "ready" &&
      (!requiredChartIds.size || requiredChartIds.has(draft.chart_id)),
  ).length;
  const failedCount = chartDrafts.filter(
    (draft) => draft.status === "failed",
  ).length;
  const expectedCount =
    session?.expected_chart_count && session.expected_chart_count > 0
      ? session.expected_chart_count
      : (session?.definition?.charts.length ?? 0);
  const readyCount = chartDrafts.length
    ? persistedReadyCount
    : (session?.definition?.charts.length ?? 0);
  const completeVisibleResult =
    session?.status === "preview" &&
    Boolean(session.definition) &&
    readyCount === expectedCount &&
    Object.keys(receipts).length === session?.definition?.charts.length;
  const pendingIntents =
    session?.plan?.intents
      .filter(
        (intent) =>
          chartDrafts.find((draft) => draft.chart_id === intent.chart_id)
            ?.status !== "ready" &&
          !(session?.status === "preview" && intent.required === false),
      )
      .sort((left, right) => left.order - right.order) ?? [];

  return (
    <aside
      data-testid="chat-dashboard-panel"
      className="flex w-[54%] min-w-[520px] max-w-[980px] flex-none flex-col border-l border-[var(--color-border)] bg-[var(--color-bg)]"
    >
      <div className="flex h-11 flex-none items-center justify-between border-b border-[var(--color-border)] px-3">
        <div className="flex min-w-0 items-center gap-2">
          <LayoutDashboard className="h-3.5 w-3.5 flex-none text-[var(--color-success)]" />
          <span className="truncate text-xs font-medium text-[var(--color-text)]">
            {session?.definition?.name ??
              session?.plan?.name ??
              "Dashboard preview"}
          </span>
          {session && (
            <span className="flex-none rounded-full bg-[var(--color-bg-card)] px-2 py-0.5 text-[10px] uppercase tracking-wider text-[var(--color-text-dim)]">
              {session.status === "building" ||
              session.status === "partial_failed"
                ? `${readyCount}/${expectedCount} ready`
                : session.status === "preview"
                  ? `Draft ${session.draft_revision}`
                  : "Saved"}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          {session?.status === "preview" && (
            <>
              <button
                type="button"
                disabled={controlsDisabled}
                onClick={() => void discard()}
                className="rounded-md px-2.5 py-1.5 text-[11px] font-medium text-[var(--color-text-muted)] hover:bg-[var(--color-bg-hover)] disabled:opacity-40"
              >
                Discard
              </button>
              <button
                type="button"
                disabled={
                  controlsDisabled ||
                  !completeVisibleResult ||
                  (session.requires_custom_sql_confirmation &&
                    !session.custom_sql_confirmed)
                }
                onClick={() => void apply()}
                className="inline-flex items-center gap-1.5 rounded-md bg-[var(--color-text)] px-2.5 py-1.5 text-[11px] font-medium text-[var(--color-bg)] disabled:opacity-40"
              >
                {busy ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <Check className="h-3 w-3" />
                )}
                Apply
              </button>
            </>
          )}
          {session?.status === "partial_failed" && (
            <button
              type="button"
              disabled={busy || failedCount === 0}
              onClick={() => void retryFailed()}
              title={chartDrafts
                .filter((draft) => draft.status === "failed")
                .map((draft) => draft.safe_error)
                .filter(Boolean)
                .join("\n")}
              className="inline-flex items-center gap-1.5 rounded-md bg-[var(--color-text)] px-2.5 py-1.5 text-[11px] font-medium text-[var(--color-bg)] disabled:opacity-40"
            >
              {busy && <Loader2 className="h-3 w-3 animate-spin" />}
              Retry failed charts
            </button>
          )}
          {session?.status !== "preview" && session?.dashboard_id && (
            <Link
              href={`/dashboards/${encodeURIComponent(session.dashboard_id)}`}
              className="inline-flex items-center gap-1.5 rounded-md bg-[var(--color-text)] px-2.5 py-1.5 text-[11px] font-medium text-[var(--color-bg)]"
            >
              Go to dashboard
              <ArrowUpRight className="h-3 w-3" />
            </Link>
          )}
          <button
            type="button"
            onClick={onClose}
            aria-label="Close dashboard preview"
            className="rounded p-1.5 text-[var(--color-text-dim)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
      {visibleUpdateLabel && (
        <div
          role="status"
          aria-live="polite"
          className="flex flex-none items-center gap-3 border-b border-[var(--color-success)]/20 bg-[var(--color-success)]/5 px-4 py-2.5"
        >
          <div className="relative flex h-7 w-7 flex-none items-center justify-center rounded-lg border border-[var(--color-success)]/25 bg-[var(--color-bg-card)]">
            <Loader2 className="h-3.5 w-3.5 animate-spin text-[var(--color-success)]" />
          </div>
          <div className="min-w-0">
            <p className="truncate text-xs font-medium text-[var(--color-text)]">
              {visibleUpdateLabel}
            </p>
            <p className="mt-0.5 text-[10px] text-[var(--color-text-dim)]">
              Showing the last validated draft until this revision is ready.
            </p>
          </div>
        </div>
      )}
      {session?.requires_custom_sql_confirmation &&
        !session.custom_sql_confirmed && (
          <div className="flex items-center justify-between gap-3 border-b border-amber-500/20 bg-amber-500/5 px-4 py-2 text-xs text-[var(--color-text-muted)]">
            <span>Custom SQL must be confirmed before it can run.</span>
            <div className="flex gap-2">
              <button
                disabled={controlsDisabled}
                onClick={() => void confirmSql("decline")}
                className="rounded px-2 py-1 hover:bg-[var(--color-bg-hover)]"
              >
                Decline
              </button>
              <button
                disabled={controlsDisabled}
                onClick={() => void confirmSql("confirm")}
                className="rounded bg-[var(--color-text)] px-2 py-1 text-[var(--color-bg)]"
              >
                Confirm SQL
              </button>
            </div>
          </div>
        )}
      <div className="relative min-h-0 flex-1 overflow-auto">
        {!session && !error && (
          <div className="flex h-full items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-[var(--color-text-dim)]" />
          </div>
        )}
        {error && (
          <div className="flex h-full items-center justify-center px-8 text-center text-sm text-[var(--color-text-muted)]">
            Dashboard preview is unavailable.
          </div>
        )}
        {session && !runtimeStylesReady && (
          <div
            data-testid="dashboard-preview-style-loading"
            className="absolute inset-x-0 top-0 z-10 flex min-h-60 items-center justify-center gap-2 text-xs text-[var(--color-text-muted)]"
          >
            <Loader2 className="h-4 w-4 animate-spin" />
            Preparing dashboard canvas…
          </div>
        )}
        {session && (
          <div
            ref={runtimeStyleProbe}
            data-testid="dashboard-preview-runtime-stage"
            className={dashboardStyles.styleReadinessProbe}
            style={{ visibility: runtimeStylesReady ? "visible" : "hidden" }}
            aria-hidden={!runtimeStylesReady}
          >
            {session.definition && (
              <DashboardRuntimeProvider
                key={`${session.id}:${session.custom_sql_confirmed}`}
                dashboardId={session.dashboard_id ?? `draft:${session.id}`}
                versionId={
                  session.applied_version_id ??
                  session.base_version_id ??
                  `draft:${session.id}`
                }
                definition={session.definition}
                authoringSessionId={
                  ["building", "partial_failed", "preview"].includes(
                    session.status,
                  )
                    ? session.id
                    : undefined
                }
                onVisibleReceiptsChange={setReceipts}
                analysisEnabled={false}
                queriesEnabled={queriesEnabled}
              />
            )}
            {pendingIntents.length > 0 && (
              <div
                data-testid="dashboard-progressive-skeletons"
                className="grid grid-cols-12 gap-3 px-4 pb-6"
              >
                {pendingIntents.map((intent) => {
                  const draft = chartDrafts.find(
                    (item) => item.chart_id === intent.chart_id,
                  );
                  const failed = draft?.status === "failed";
                  return (
                    <div
                      key={intent.tile_id}
                      data-testid={`dashboard-chart-placeholder-${intent.chart_id}`}
                      data-status={draft?.status ?? "pending"}
                      title={
                        failed ? (draft?.safe_error ?? undefined) : undefined
                      }
                      className={`flex min-h-40 flex-col items-center justify-center rounded-xl border px-4 text-center ${
                        failed
                          ? "border-red-500/30 bg-red-500/5 text-red-300"
                          : "border-[var(--color-border)] bg-[var(--color-bg-card)] text-[var(--color-text-dim)]"
                      }`}
                      style={{
                        gridColumn: `span ${Math.max(1, Math.min(12, Math.ceil(intent.layout.w / 3)))}`,
                      }}
                    >
                      {!failed && (
                        <Loader2 className="mb-2 h-4 w-4 animate-spin" />
                      )}
                      <strong className="text-xs text-[var(--color-text)]">
                        {intent.label}
                      </strong>
                      <span className="mt-1 text-[10px]">
                        {failed ? draft?.safe_error : "Building governed chart"}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </div>
    </aside>
  );
}
