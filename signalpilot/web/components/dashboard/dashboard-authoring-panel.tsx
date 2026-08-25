"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Check, MessageSquare, Sparkles, X } from "lucide-react";

import { request } from "~/lib/api";
import type { DashboardDefinition } from "~/lib/dashboard/contracts";
import type { DashboardQueryReceipt } from "~/lib/dashboard/api-data-source";
import { DashboardRuntimeProvider } from "~/components/dashboard/dashboard-runtime-provider";
import { DashboardSpinner } from "~/components/dashboard/dashboard-loading-state";

import styles from "./dashboard-runtime.module.css";

export type DashboardAuthoringEvent = {
  id: string;
  sequence: number;
  kind:
    | "user"
    | "assistant"
    | "progress"
    | "validation"
    | "confirmation"
    | "system";
  status: "info" | "success" | "error" | "pending";
  message: string;
  metadata: Record<string, unknown>;
};

export type DashboardAuthoringSession = {
  id: string;
  thread_id: string;
  dashboard_id: string | null;
  base_version_id: string | null;
  definition: DashboardDefinition;
  operations: Array<Record<string, unknown>>;
  summary: string;
  status: string;
  requires_custom_sql_confirmation: boolean;
  custom_sql_confirmed: boolean;
  custom_sql_chart_ids: string[];
  draft_revision: number;
  events: DashboardAuthoringEvent[];
};

type AppliedDashboard = { dashboard: { id: string }; version: { id: string } };

export function DashboardAuthoringWorkspace({
  dashboardId,
  versionId,
  baseDefinition,
  createContext,
  contextControls,
  session,
  onSession,
  onApplied,
  onDiscard,
  onClose,
}: {
  dashboardId?: string;
  versionId?: string;
  baseDefinition?: DashboardDefinition;
  createContext?: { project_id: string; branch: string; timezone: string };
  contextControls?: ReactNode;
  session?: DashboardAuthoringSession;
  onSession: (session: DashboardAuthoringSession | undefined) => void;
  onApplied: (detail: AppliedDashboard) => void;
  onDiscard: () => void;
  onClose?: () => void;
}) {
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [busyLabel, setBusyLabel] = useState("");
  const [error, setError] = useState<string>();
  const [mobileView, setMobileView] = useState<"chat" | "preview">("chat");
  const [receipts, setReceipts] = useState<
    Record<string, DashboardQueryReceipt>
  >({});
  const transcriptRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const transcript = transcriptRef.current;
    if (!transcript) return;
    if (typeof transcript.scrollTo === "function") {
      transcript.scrollTo({ top: transcript.scrollHeight, behavior: "smooth" });
    } else {
      transcript.scrollTop = transcript.scrollHeight;
    }
  }, [session?.events.length, busy]);

  const refreshSession = async () => {
    if (!session) return;
    try {
      onSession(
        await request<DashboardAuthoringSession>(
          `/api/dashboard-authoring/sessions/${session.id}`,
        ),
      );
    } catch {
      // Keep the original safe error if recovery also fails.
    }
  };

  const mutate = async (path: string, options: RequestInit, label: string) => {
    setBusy(true);
    setBusyLabel(label);
    setError(undefined);
    try {
      const updated = await request<DashboardAuthoringSession>(path, options);
      onSession(updated);
      return updated;
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "The draft could not be updated",
      );
      await refreshSession();
    } finally {
      setBusy(false);
      setBusyLabel("");
    }
  };

  const visibleDefinition = session?.definition ?? baseDefinition;
  return (
    <section
      className={styles.authoringWorkspace}
      aria-label="Dashboard AI authoring"
      data-mobile-view={mobileView}
    >
      <div className={styles.authoringMobileTabs} aria-label="Authoring view">
        <button
          type="button"
          aria-pressed={mobileView === "chat"}
          onClick={() => setMobileView("chat")}
        >
          Chat
        </button>
        <button
          type="button"
          aria-pressed={mobileView === "preview"}
          onClick={() => setMobileView("preview")}
        >
          Preview
        </button>
      </div>
      <aside className={styles.authoringConversation}>
        <header>
          <div>
            <h1>
              <MessageSquare size={18} aria-hidden="true" /> Dashboard author
            </h1>
          </div>
          {onClose ? (
            <button
              type="button"
              onClick={onClose}
              aria-label="Close authoring"
            >
              <X size={17} aria-hidden="true" />
            </button>
          ) : null}
        </header>
        {contextControls ? (
          <div className={styles.authoringContext}>{contextControls}</div>
        ) : (
          <div className={styles.authoringContext}>
            <span>Immutable base</span>
            <strong>{baseDefinition?.name ?? "Current dashboard"}</strong>
            <small>Draft changes stay private until Apply.</small>
          </div>
        )}
        <div
          className={styles.authoringTranscript}
          ref={transcriptRef}
          aria-live="polite"
        >
          {!session?.events.length ? (
            <div className={styles.authoringWelcome}>
              <Sparkles size={20} aria-hidden="true" />
              <strong>What should this dashboard explain?</strong>
              <p>
                Ask for approved metrics and fields. Follow-ups refine the same
                unsaved draft without rewriting unrelated charts.
              </p>
            </div>
          ) : null}
          {session?.events.map((event) => (
            <article
              key={event.id}
              className={`${styles.authoringEvent} ${styles[`authoringEvent_${event.kind}`]}`}
              data-status={event.status}
            >
              <span>{event.kind === "user" ? "You" : event.kind}</span>
              <p>{event.message}</p>
            </article>
          ))}
          {busy ? (
            <article className={styles.authoringEvent} data-status="pending">
              <span>Progress</span>
              <p>
                <DashboardSpinner size="small" /> {busyLabel}
              </p>
            </article>
          ) : null}
        </div>
        {session?.requires_custom_sql_confirmation &&
        !session.custom_sql_confirmed ? (
          <div className={styles.authoringConfirmation}>
            <strong>Low-confidence SQL needs your decision</strong>
            <p>
              {session.custom_sql_chart_ids.join(", ")} uses custom SQL. Confirm
              to execute it, or decline to retain the remaining governed draft.
            </p>
            <div>
              <button
                type="button"
                disabled={busy}
                onClick={() =>
                  void mutate(
                    `/api/dashboard-authoring/sessions/${session.id}/confirm-custom-sql`,
                    { method: "POST" },
                    "Confirming custom SQL…",
                  )
                }
              >
                Confirm SQL
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() =>
                  void mutate(
                    `/api/dashboard-authoring/sessions/${session.id}/decline-custom-sql`,
                    { method: "POST" },
                    "Removing custom SQL…",
                  )
                }
              >
                Decline
              </button>
            </div>
          </div>
        ) : null}
        <form
          className={styles.authoringComposer}
          onSubmit={(event) => {
            event.preventDefault();
            const trimmed = prompt.trim();
            if (!trimmed || busy) return;
            const continuation = Boolean(session);
            const path = continuation
              ? `/api/dashboard-authoring/sessions/${session?.id}/messages`
              : "/api/dashboard-authoring/sessions";
            const body = continuation
              ? { prompt: trimmed }
              : {
                  prompt: trimmed,
                  dashboard_id: dashboardId,
                  base_version_id: versionId,
                  ...createContext,
                };
            void mutate(
              path,
              { method: "POST", body: JSON.stringify(body) },
              continuation
                ? "Refining and validating the current draft…"
                : "Resolving context and drafting charts…",
            ).then((updated) => {
              if (!updated) return;
              setPrompt("");
              if (!dashboardId) {
                const url = new URL(window.location.href);
                url.searchParams.set("authoring", updated.id);
                window.history.replaceState({}, "", url);
              }
            });
          }}
        >
          <label htmlFor="dashboard-authoring-prompt">
            {session ? "Refine this draft" : "Describe the dashboard"}
          </label>
          <textarea
            id="dashboard-authoring-prompt"
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            disabled={
              busy ||
              Boolean(
                session?.requires_custom_sql_confirmation &&
                  !session.custom_sql_confirmed,
              )
            }
            rows={3}
            placeholder={
              session
                ? "Make the revenue trend a line chart and keep everything else."
                : "Create an executive dashboard for revenue, margin, and customers…"
            }
          />
          {error ? <p className={styles.errorState}>{error}</p> : null}
          <button
            type="submit"
            disabled={
              busy ||
              !prompt.trim() ||
              Boolean(
                session?.requires_custom_sql_confirmation &&
                  !session.custom_sql_confirmed,
              ) ||
              (!session && !dashboardId && !createContext?.project_id)
            }
          >
            <Sparkles size={15} aria-hidden="true" />
            {session ? "Send refinement" : "Create preview"}
          </button>
        </form>
      </aside>
      <div className={styles.authoringCanvas}>
        <header>
          <div>
            <strong>
              {visibleDefinition?.name ?? "Waiting for your first request"}
            </strong>
          </div>
          {session ? (
            <small>
              {session.status === "preview"
                ? `Draft ${session.draft_revision}`
                : "Saved thread"}
            </small>
          ) : null}
          <div className={styles.authoringApplyActions}>
            <button
              className={styles.authoringToolbarButton}
              type="button"
              disabled={busy || !session || session.status !== "preview"}
              onClick={() => {
                if (!session) return;
                setBusy(true);
                setBusyLabel("Discarding draft…");
                setError(undefined);
                void request<DashboardAuthoringSession>(
                  `/api/dashboard-authoring/sessions/${session.id}/discard`,
                  { method: "POST" },
                )
                  .then(() => {
                    onSession(undefined);
                    onDiscard();
                  })
                  .catch((cause) => setError(String(cause)))
                  .finally(() => setBusy(false));
              }}
            >
              Discard
            </button>
            <button
              className={styles.authoringToolbarButton}
              type="button"
              disabled={
                busy ||
                !session ||
                session.status !== "preview" ||
                (session.requires_custom_sql_confirmation &&
                  !session.custom_sql_confirmed)
              }
              onClick={() => {
                if (!session) return;
                setBusy(true);
                setBusyLabel("Applying exact visible draft…");
                setError(undefined);
                void request<AppliedDashboard>(
                  `/api/dashboard-authoring/sessions/${session.id}/apply`,
                  {
                    method: "POST",
                    body: JSON.stringify({
                      expected_current_version_id: versionId,
                      visible_complete_result_ids: Object.values(receipts)
                        .filter(
                          (receipt) => receipt.completeness === "complete",
                        )
                        .map((receipt) => receipt.dashboard_result_id),
                    }),
                  },
                )
                  .then(onApplied)
                  .catch((cause) => setError(String(cause)))
                  .finally(() => setBusy(false));
              }}
            >
              <Check size={15} aria-hidden="true" /> Apply
            </button>
          </div>
        </header>
        <div className={styles.authoringPreviewCanvas}>
          {session ? (
            <DashboardRuntimeProvider
              key={`${session.id}:${session.draft_revision}:${session.custom_sql_confirmed}`}
              dashboardId={`draft:${session.id}`}
              versionId={`draft:${session.id}`}
              definition={session.definition}
              authoringSessionId={session.id}
              onVisibleReceiptsChange={setReceipts}
              analysisEnabled={false}
            />
          ) : visibleDefinition ? (
            <DashboardRuntimeProvider
              dashboardId={dashboardId ?? "authoring-base"}
              versionId={versionId ?? "authoring-base"}
              definition={visibleDefinition}
              analysisEnabled={false}
            />
          ) : (
            <div className={styles.authoringEmptyPreview}>
              <Sparkles size={28} aria-hidden="true" />
              <p>
                The governed dashboard preview will remain here while you refine
                it.
              </p>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

export function DashboardAuthoringPanel({
  dashboardId,
  versionId,
  baseDefinition,
  onApplied,
}: {
  dashboardId: string;
  versionId: string;
  baseDefinition: DashboardDefinition;
  onApplied: (detail: AppliedDashboard) => void;
}) {
  const [open, setOpen] = useState(false);
  const [session, setSession] = useState<DashboardAuthoringSession>();

  useEffect(() => {
    if (!open || session) return;
    void request<DashboardAuthoringSession | null>(
      `/api/dashboards/${dashboardId}/active-authoring-session`,
    ).then((active) => setSession(active ?? undefined));
  }, [dashboardId, open, session]);

  if (!open) {
    return (
      <button
        className={styles.authoringLauncher}
        type="button"
        onClick={() => setOpen(true)}
      >
        <Sparkles size={16} aria-hidden="true" /> Edit with AI
      </button>
    );
  }
  if (typeof document === "undefined") return null;
  return createPortal(
    <div
      className={styles.authoringOverlay}
      data-testid="dashboard-authoring-overlay"
    >
      <DashboardAuthoringWorkspace
        dashboardId={dashboardId}
        versionId={versionId}
        baseDefinition={baseDefinition}
        session={session}
        onSession={setSession}
        onApplied={onApplied}
        onDiscard={() => setOpen(false)}
        onClose={() => setOpen(false)}
      />
    </div>,
    document.body,
  );
}
