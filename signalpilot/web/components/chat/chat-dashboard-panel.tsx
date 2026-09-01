"use client";

import { Check, LayoutDashboard, Loader2, X } from "lucide-react";
import { useState } from "react";
import useSWR from "swr";

import { DashboardRuntimeProvider } from "~/components/dashboard/dashboard-runtime-provider";
import type { DashboardAuthoringSession } from "~/components/dashboard/dashboard-authoring-panel";
import type { DashboardQueryReceipt } from "~/lib/dashboard/api-data-source";
import { request } from "~/lib/api";
import { useToast } from "~/components/ui/toast";

type AppliedDashboard = { dashboard: { id: string }; version: { id: string } };

export function ChatDashboardPanel({
  sessionId,
  onClose,
}: {
  sessionId: string;
  onClose: () => void;
}) {
  const { toast } = useToast();
  const {
    data: session,
    error,
    mutate,
  } = useSWR(`dashboard-authoring-session:${sessionId}`, () =>
    request<DashboardAuthoringSession>(
      `/api/dashboard-authoring/sessions/${sessionId}`,
    ),
  );
  const [busy, setBusy] = useState(false);
  const [receipts, setReceipts] = useState<
    Record<string, DashboardQueryReceipt>
  >({});

  const confirmSql = async (decision: "confirm" | "decline") => {
    if (!session) return;
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
    if (!session) return;
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
    if (!session) return;
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
                disabled={busy}
                onClick={() => void discard()}
                className="rounded-md px-2.5 py-1.5 text-[11px] font-medium text-[var(--color-text-muted)] hover:bg-[var(--color-bg-hover)] disabled:opacity-40"
              >
                Discard
              </button>
              <button
                type="button"
                disabled={
                  busy ||
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
      {session?.requires_custom_sql_confirmation &&
        !session.custom_sql_confirmed && (
          <div className="flex items-center justify-between gap-3 border-b border-amber-500/20 bg-amber-500/5 px-4 py-2 text-xs text-[var(--color-text-muted)]">
            <span>Custom SQL must be confirmed before it can run.</span>
            <div className="flex gap-2">
              <button
                disabled={busy}
                onClick={() => void confirmSql("decline")}
                className="rounded px-2 py-1 hover:bg-[var(--color-bg-hover)]"
              >
                Decline
              </button>
              <button
                disabled={busy}
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
        {session && (
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
        )}
      </div>
    </aside>
  );
}
