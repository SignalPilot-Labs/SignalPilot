"use client";

/**
 * Active sessions section — shows current session + others with per-row revoke
 * and bulk "sign out all other sessions".
 * Uses user.getSessions() (not useSessionList).
 */

import React, { useState, useEffect, useCallback } from "react";
import { Monitor, Loader2 } from "lucide-react";
import { useUser, useSession, useReverification } from "@clerk/nextjs";
import type { SessionWithActivitiesResource } from "@clerk/types";
import { SectionHeader } from "@/components/ui/section-header";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useToast } from "@/components/ui/toast";
import { ERROR_CLASS, NEUTRAL_CLASS } from "@/components/auth/auth-primitives";
import { isReverificationCancelledError } from "@/lib/security/use-reverify";
import { formatClerkError } from "@/lib/security/clerk-errors";
import { SessionRow } from "./session-row";

export function ActiveSessionsSection() {
  const { user } = useUser();
  const { session: currentSession } = useSession();

  const [sessions, setSessions] = useState<SessionWithActivitiesResource[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // Confirm dialogs
  const [revokeTarget, setRevokeTarget] = useState<SessionWithActivitiesResource | null>(null);
  const [bulkConfirmOpen, setBulkConfirmOpen] = useState(false);

  const fetchSessions = useCallback(async () => {
    if (!user) return;
    setLoading(true);
    try {
      const list = await user.getSessions();
      setSessions(list);
    } catch (err) {
      setError(formatClerkError(err));
    } finally {
      setLoading(false);
    }
  }, [user]);

  useEffect(() => {
    void fetchSessions();
  }, [fetchSessions]);

  const { toast } = useToast();

  const reverifiedRevoke = useReverification(
    (s: SessionWithActivitiesResource) => s.revoke(),
  );

  const reverifiedBulkRevoke = useReverification(
    async (others: SessionWithActivitiesResource[]) => {
      for (const s of others) {
        await s.revoke();
      }
    },
  );

  async function handleRevokeConfirm() {
    if (!revokeTarget) return;
    const target = revokeTarget;
    setRevokeTarget(null);
    setError(null);
    setNotice(null);
    try {
      await reverifiedRevoke(target);
      toast("session revoked", "success");
      await fetchSessions();
    } catch (err) {
      if (isReverificationCancelledError(err)) {
        setNotice("reverification required to revoke session");
      } else {
        setError(formatClerkError(err));
      }
    }
  }

  async function handleBulkRevokeConfirm() {
    setBulkConfirmOpen(false);
    setError(null);
    setNotice(null);
    const others = (sessions ?? []).filter((s) => s.id !== currentSession?.id);
    if (others.length === 0) return;
    try {
      await reverifiedBulkRevoke(others);
      toast("signed out of all other sessions", "success");
    } catch (err) {
      if (isReverificationCancelledError(err)) {
        setNotice("reverification required to sign out other sessions");
      } else {
        setError(formatClerkError(err));
      }
    } finally {
      // Refetch to show actual state (partial-failure-safe)
      await fetchSessions();
    }
  }

  const current = sessions?.find((s) => s.id === currentSession?.id) ?? null;
  const others = (sessions ?? []).filter((s) => s.id !== currentSession?.id);

  return (
    <section className="mb-8">
      <SectionHeader icon={Monitor} title="active sessions" />
      <div
        className="border border-[var(--color-border)] bg-[var(--color-bg-card)]"
        aria-busy={loading}
        aria-live="polite"
      >
        {loading && sessions === null ? (
          <div className="p-4 space-y-3">
            {[1, 2].map((i) => (
              <div key={i} className="h-12 bg-[var(--color-bg-hover)] animate-pulse" />
            ))}
          </div>
        ) : (
          <>
            <div role="alert" aria-live="assertive" aria-atomic="true" className="px-4">
              {error && <p className={`${ERROR_CLASS} pt-3`}>{error}</p>}
            </div>
            <div role="status" aria-live="polite" aria-atomic="true" className="px-4">
              {notice && <p className={`${NEUTRAL_CLASS} pt-3`}>{notice}</p>}
            </div>

            {/* Current session */}
            {current && (
              <SessionRow session={current} isCurrent />
            )}

            {/* Divider if there are other sessions */}
            {others.length > 0 && (
              <div className="h-px bg-[var(--color-border)] mx-4" />
            )}

            {/* Other sessions */}
            {others.map((s) => (
              <SessionRow
                key={s.id}
                session={s}
                isCurrent={false}
                onRevoke={setRevokeTarget}
              />
            ))}

            {/* Bulk sign out */}
            {others.length > 0 && (
              <div className="px-4 py-3 border-t border-[var(--color-border)]">
                <button
                  type="button"
                  onClick={() => setBulkConfirmOpen(true)}
                  className="text-[11px] text-[var(--color-text-dim)] hover:text-[var(--color-error)] tracking-wider font-mono uppercase transition-colors focus:outline-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-text)]"
                >
                  sign out all other sessions
                </button>
              </div>
            )}
          </>
        )}
      </div>

      {/* Per-row revoke confirm */}
      <ConfirmDialog
        open={revokeTarget !== null}
        title="revoke session"
        message={
          revokeTarget
            ? `Sign out the session on ${revokeTarget.latestActivity.browserName ?? "this device"}? It will be revoked immediately.`
            : ""
        }
        confirmLabel="revoke"
        cancelLabel="cancel"
        variant="danger"
        onConfirm={handleRevokeConfirm}
        onCancel={() => setRevokeTarget(null)}
      />

      {/* Bulk revoke confirm */}
      <ConfirmDialog
        open={bulkConfirmOpen}
        title="sign out other sessions"
        message={`Sign out of all ${others.length} other session${others.length !== 1 ? "s" : ""}? This will revoke access on all other devices.`}
        confirmLabel="sign out all"
        cancelLabel="cancel"
        variant="danger"
        onConfirm={handleBulkRevokeConfirm}
        onCancel={() => setBulkConfirmOpen(false)}
      />
    </section>
  );
}
