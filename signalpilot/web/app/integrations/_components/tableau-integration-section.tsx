"use client";

import { useEffect } from "react";
import { Loader2, RefreshCw, Trash2 } from "lucide-react";
import type { TableauIntegrationInfo } from "~/lib/api";
import { TableauIcon } from "~/components/branding/tableau-icon";
import { ReadOnlyNote } from "~/components/access/read-only-note";
import { ConfirmDialog } from "~/components/ui/confirm-dialog";
import { StatusDot } from "~/components/ui/data-viz";
import { SectionHeader } from "~/components/ui/section-header";
import { Switch } from "~/components/ui/switch";
import { TimeAgo } from "~/components/ui/time-ago";
import { TableauCredentialsForm } from "./tableau-credentials-form";
import { useTableauIntegration } from "./use-tableau-integration";

export const TABLEAU_EXPLAINER =
  "Chat agents can find, build, and edit workbooks on this site. Data sources they publish use your SignalPilot connection credentials.";

const SECONDARY_BUTTON =
  "flex items-center gap-1.5 px-3 py-1.5 text-[12px] text-[var(--color-text-dim)] border border-[var(--color-border)] rounded-[10px] transition-colors duration-150 disabled:opacity-30";

/** The status line under the header: who the token signs in as, or why not. */
function TableauStatusLine({ info }: { info: TableauIntegrationInfo }) {
  if (info.status === "ok") {
    const who = info.user_name ?? "unknown user";
    return (
      <div data-testid="tableau-status" className="flex flex-wrap items-center gap-2">
        <StatusDot status="healthy" size={4} />
        <span className="text-[13px] text-[var(--color-success)] font-medium">
          Connected as {who}
          {info.site_role ? ` (${info.site_role})` : ""}
        </span>
        {info.verified_at ? (
          <span className="text-[11px] text-[var(--color-text-dim)]">
            verified <TimeAgo timestamp={info.verified_at} live /> ago
          </span>
        ) : null}
      </div>
    );
  }
  if (info.status === "error") {
    return (
      <div data-testid="tableau-status" className="flex items-start gap-2">
        <span className="mt-1.5"><StatusDot status="error" size={4} /></span>
        <span className="text-[13px] text-[var(--color-error)] break-words">
          {info.last_error || "Tableau sign-in failed"}
        </span>
      </div>
    );
  }
  return (
    <div data-testid="tableau-status" className="flex items-center gap-2">
      <StatusDot status="warning" size={4} />
      <span className="text-[13px] text-[var(--color-text)]">Not verified yet</span>
    </div>
  );
}

/**
 * The Tableau site card on /integrations. Admins save, test, toggle, and
 * disconnect; members see the status only. Anchor: `#tableau`.
 */
export function TableauIntegrationSection({ readOnly = false }: { readOnly?: boolean }) {
  const state = useTableauIntegration();
  const { info, loading, loadError } = state;
  const configured = Boolean(info?.configured);

  // The page renders a skeleton first, so the browser's own anchor jump
  // finds nothing. Scroll once the card has content.
  useEffect(() => {
    if (loading || typeof window === "undefined") return;
    if (window.location.hash !== "#tableau") return;
    document.getElementById("tableau")?.scrollIntoView?.({ block: "start" });
  }, [loading]);

  return (
    <section id="tableau" data-testid="tableau-integration" className="mb-8 scroll-mt-8">
      <div className="flex items-center justify-between mb-4">
        <SectionHeader icon={TableauIcon} title="tableau" />
      </div>

      <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] rounded-[14px] p-5">
        {loading ? (
          <div className="flex items-center gap-2 text-[12px] text-[var(--color-text-dim)]">
            <Loader2 className="w-3 h-3 animate-spin" />
            checking tableau
          </div>
        ) : loadError || !info ? (
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-2">
              <StatusDot status="error" size={4} />
              <span className="text-[12px] text-[var(--color-text-dim)]">failed to load</span>
            </div>
            <button
              onClick={() => void state.fetchIntegration()}
              className={`${SECONDARY_BUTTON} hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)]`}
            >
              retry
            </button>
          </div>
        ) : (
          <div className="space-y-4">
            <p className="text-[12px] leading-5 text-[var(--color-text-dim)]">{TABLEAU_EXPLAINER}</p>

            {configured ? (
              <div className="space-y-3">
                <TableauStatusLine info={info} />
                <div className="space-y-1 text-[11px] text-[var(--color-text-dim)]">
                  <p>
                    site: <span className="text-[var(--color-text-muted)] font-mono break-all">{info.site_url || info.server_url || "-"}</span>
                  </p>
                  <p>
                    token name: <span className="text-[var(--color-text-muted)] font-mono">{info.pat_name || "-"}</span>
                  </p>
                </div>
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div className="flex items-center gap-3">
                    <Switch
                      size="sm"
                      checked={info.enabled}
                      onCheckedChange={(next) => void state.handleToggleEnabled(next)}
                      disabled={readOnly}
                      busy={state.toggling}
                      aria-labelledby="tableau-enabled-label"
                      data-testid="tableau-enabled-switch"
                    />
                    <span id="tableau-enabled-label" className="text-[12px] text-[var(--color-text)]">
                      Enabled for chat
                    </span>
                  </div>
                  {!readOnly && (
                    <div className="flex items-center gap-1.5">
                      <button
                        onClick={() => void state.handleTest()}
                        disabled={state.testing}
                        className={`${SECONDARY_BUTTON} hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)]`}
                      >
                        {state.testing ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
                        Test again
                      </button>
                      <button
                        onClick={() => state.setConfirmDisconnect(true)}
                        disabled={state.disconnecting}
                        className={`${SECONDARY_BUTTON} hover:border-[var(--color-error)]/50 hover:text-[var(--color-error)]`}
                      >
                        <Trash2 className="w-3 h-3" />
                        Disconnect
                      </button>
                    </div>
                  )}
                </div>
              </div>
            ) : readOnly ? (
              <div className="flex items-center gap-2">
                <StatusDot status="unknown" size={4} />
                <span className="text-[13px] text-[var(--color-text)]">Not connected</span>
              </div>
            ) : null}

            {readOnly ? (
              <ReadOnlyNote block>the org Tableau site chat agents use</ReadOnlyNote>
            ) : (
              <TableauCredentialsForm state={state} />
            )}
          </div>
        )}
      </div>

      <ConfirmDialog
        open={state.confirmDisconnect}
        title="Disconnect Tableau?"
        titleCase="sentence"
        message="Chat agents lose access to this Tableau site. The token is deleted from SignalPilot; workbooks on Tableau stay as they are."
        confirmLabel="disconnect"
        onConfirm={() => void state.handleDisconnect()}
        onCancel={() => state.setConfirmDisconnect(false)}
      />
    </section>
  );
}
