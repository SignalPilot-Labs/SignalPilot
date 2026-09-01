"use client";

import { Check, LayoutDashboard, Loader2, X } from "lucide-react";
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
  onClose,
}: {
  sessionId: string;
  updateLabel?: string | null;
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
    {
      refreshInterval: updateLabel ? 1_000 : 0,
      revalidateOnFocus: false,
    },
  );
  const [busy, setBusy] = useState(false);
  const [receipts, setReceipts] = useState<
    Record<string, DashboardQueryReceipt>
  >({});
  const [syncingRevision, setSyncingRevision] = useState(false);
  const [runtimeStylesReady, setRuntimeStylesReady] = useState(false);
  const runtimeStyleProbe = useRef<HTMLDivElement>(null);
  const wasUpdating = useRef(false);
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

  return (
    <aside
      data-testid="chat-dashboard-panel"
      className="flex w-[54%] min-w-[520px] max-w-[980px] flex-none flex-col border-l border-[var(--color-border)] bg-[var(--color-bg)]"
    >
      <div className="flex h-11 flex-none items-center justify-between border-b border-[var(--color-border)] px-3">
        <div className="flex min-w-0 items-center gap-2">
          <LayoutDashboard className="h-3.5 w-3.5 flex-none text-[var(--color-success)]" />
          <span className="truncate text-xs font-medium text-[var(--color-text)]">
            {session?.definition.name ?? "Dashboard preview"}
          </span>
          {session && (
            <span className="flex-none rounded-full bg-[var(--color-bg-card)] px-2 py-0.5 text-[10px] uppercase tracking-wider text-[var(--color-text-dim)]">
              {session.status === "preview"
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
            <DashboardRuntimeProvider
              key={`${session.id}:${session.draft_revision}:${session.custom_sql_confirmed}`}
              dashboardId={session.dashboard_id ?? `draft:${session.id}`}
              versionId={
                session.applied_version_id ??
                session.base_version_id ??
                `draft:${session.id}`
              }
              definition={session.definition}
              authoringSessionId={
                session.status === "preview" ? session.id : undefined
              }
              onVisibleReceiptsChange={setReceipts}
              analysisEnabled={false}
            />
          </div>
        )}
      </div>
    </aside>
  );
}
