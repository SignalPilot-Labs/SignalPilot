"use client";

/**
 * Pending invitations list + invite form (admin only).
 * Invite: email FieldRow + RoleSelect + send button.
 * Revoke: per-row via InvitationRow.
 */

import React, { useState } from "react";
import { Mail, Loader2 } from "lucide-react";
import { useReverification, useOrganization } from "@clerk/nextjs";
import type { OrganizationResource, OrganizationInvitationResource } from "@clerk/types";
import { SectionHeader } from "@/components/ui/section-header";
import { useToast } from "@/components/ui/toast";
import {
  FIELD_INPUT_CLASS,
  PRIMARY_BTN_CLASS,
  LABEL_CLASS,
  ERROR_CLASS,
  NEUTRAL_CLASS,
  SECONDARY_BTN_CLASS,
} from "@/components/auth/auth-primitives";
import { isReverificationCancelledError } from "@/lib/security/use-reverify";
import { formatClerkError } from "@/lib/security/clerk-errors";
import type { TeamPermissions } from "@/lib/team/use-team-permissions";
import { ROLE_MEMBER, type TeamRole } from "@/lib/team/roles";
import { RoleSelect } from "./role-select";
import { InvitationRow } from "./invitation-row";

export interface TeamInvitationsSectionProps {
  org: OrganizationResource;
  perms: TeamPermissions;
}

export function TeamInvitationsSection({ org, perms }: TeamInvitationsSectionProps) {
  const { invitations } = useOrganization({
    invitations: { pageSize: 20, keepPreviousData: true },
  });

  const { toast } = useToast();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<TeamRole>(ROLE_MEMBER);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const reverifiedInvite = useReverification(
    (params: { emailAddress: string; role: string }) =>
      org.inviteMember({ emailAddress: params.emailAddress, role: params.role }),
  );

  const reverifiedRevoke = useReverification(
    (inv: OrganizationInvitationResource) => inv.revoke(),
  );

  async function handleInvite(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim()) { setError("email is required"); return; }
    setError(null);
    setNotice(null);
    setSending(true);
    try {
      await reverifiedInvite({ emailAddress: email.trim(), role });
      setEmail("");
      setRole(ROLE_MEMBER);
      toast("invitation sent", "success");
    } catch (err) {
      if (isReverificationCancelledError(err)) {
        setNotice("reverification required to send invitation");
      } else {
        setError(formatClerkError(err));
      }
    } finally {
      setSending(false);
    }
  }

  async function handleRevoke(inv: OrganizationInvitationResource) {
    setError(null);
    setNotice(null);
    try {
      await reverifiedRevoke(inv);
      toast("invitation revoked", "success");
    } catch (err) {
      if (isReverificationCancelledError(err)) {
        setNotice("reverification required to revoke invitation");
      } else {
        setError(formatClerkError(err));
      }
    }
  }

  const data = invitations?.data ?? [];
  const isLoading = invitations?.isLoading ?? false;
  const hasNextPage = invitations?.hasNextPage ?? false;

  return (
    <section className="mb-8">
      <SectionHeader icon={Mail} title="invitations" />
      <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)]">
        {/* Invite form — admin only */}
        {perms.canInvite && (
          <form onSubmit={handleInvite} className="p-6 space-y-4 border-b border-[var(--color-border)]">
            <div className="flex flex-col gap-1">
              <label htmlFor="invite-email" className={LABEL_CLASS}>invite by email</label>
              <div className="flex gap-2">
                <input
                  id="invite-email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="user@example.com"
                  className={`${FIELD_INPUT_CLASS} flex-1`}
                  autoComplete="off"
                />
                <RoleSelect
                  value={role}
                  onChange={setRole}
                  disabled={sending}
                  ariaLabel="invited member role"
                />
              </div>
            </div>

            <div role="alert" aria-live="assertive" aria-atomic="true">
              {error && <p className={ERROR_CLASS}>{error}</p>}
            </div>
            <div role="status" aria-live="polite" aria-atomic="true">
              {notice && <p className={NEUTRAL_CLASS}>{notice}</p>}
            </div>

            <button
              type="submit"
              disabled={sending || !email.trim()}
              className={PRIMARY_BTN_CLASS}
            >
              {sending ? <Loader2 className="w-3.5 h-3.5 animate-spin inline mr-2" /> : null}
              send invitation
            </button>
          </form>
        )}

        {/* Non-admin error/notice */}
        {!perms.canInvite && (
          <>
            <div role="alert" aria-live="assertive" aria-atomic="true" className="px-4">
              {error && <p className={`${ERROR_CLASS} pt-3`}>{error}</p>}
            </div>
            <div role="status" aria-live="polite" aria-atomic="true" className="px-4">
              {notice && <p className={`${NEUTRAL_CLASS} pt-3`}>{notice}</p>}
            </div>
          </>
        )}

        {/* Pending invitations list */}
        {isLoading && data.length === 0 ? (
          <div className="p-4 space-y-3" aria-busy="true">
            {[1, 2].map((i) => (
              <div key={i} className="h-8 bg-[var(--color-bg-hover)] animate-pulse" />
            ))}
          </div>
        ) : data.length === 0 ? (
          <p className={`${NEUTRAL_CLASS} p-4`}>no pending invitations.</p>
        ) : (
          <div aria-live="polite">
            {data.map((inv) => (
              <InvitationRow
                key={inv.id}
                invitation={inv}
                canRevoke={perms.canInvite}
                onRevoke={handleRevoke}
              />
            ))}
          </div>
        )}

        {hasNextPage && (
          <div className="px-4 py-3 border-t border-[var(--color-border)]">
            <button
              type="button"
              onClick={() => invitations?.fetchNext?.()}
              disabled={isLoading}
              className={`${SECONDARY_BTN_CLASS} flex items-center gap-1`}
            >
              {isLoading ? <Loader2 className="w-3 h-3 animate-spin" /> : null}
              load more
            </button>
          </div>
        )}
      </div>
    </section>
  );
}
