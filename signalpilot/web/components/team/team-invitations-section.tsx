"use client";

/**
 * Pending invitations list + invite form (admin only).
 * Invite: email FieldRow + RoleSelect + send button.
 * Revoke: per-row via InvitationRow.
 */

import React, { useEffect, useId, useState } from "react";
import { Mail } from "lucide-react";
import { InvitationListSkeleton } from "~/components/ui/list-skeletons";
import { PendingButton } from "~/components/ui/pending-button";
import { useReverification, useOrganization } from "@clerk/nextjs";
import type { OrganizationResource, OrganizationInvitationResource } from "@clerk/types";
import { SectionHeader } from "~/components/ui/section-header";
import { useToast } from "~/components/ui/toast";
import {
  FIELD_INPUT_CLASS,
  LABEL_CLASS,
  ERROR_CLASS,
  NEUTRAL_CLASS,
} from "~/components/auth/auth-primitives";
import { isReverificationCancelledError } from "~/lib/security/use-reverify";
import { formatClerkError } from "~/lib/security/clerk-errors";
import type { TeamPermissions } from "~/lib/team/use-team-permissions";
import { ROLE_MEMBER, type TeamRole } from "~/lib/team/roles";
import { RoleSelect } from "./role-select";
import { InvitationRow } from "./invitation-row";
import { getConnections } from "~/lib/api";
import { useSubscription } from "~/lib/subscription-context";

export interface TeamInvitationsSectionProps {
  org: OrganizationResource;
  perms: TeamPermissions;
}

export function TeamInvitationForm({
  org,
  defaultRole = ROLE_MEMBER,
  onInvited,
}: {
  org: OrganizationResource;
  defaultRole?: TeamRole;
  onInvited?: () => void | Promise<void>;
}) {
  const { toast } = useToast();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<TeamRole>(defaultRole);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const emailId = useId();
  const reverifiedInvite = useReverification(
    (params: { emailAddress: string; role: string }) =>
      org.inviteMember({ emailAddress: params.emailAddress, role: params.role }),
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
      setRole(defaultRole);
      await onInvited?.();
      toast("invitation sent", "success");
    } catch (err) {
      if (isReverificationCancelledError(err)) setNotice("reverification required to send invitation");
      else setError(formatClerkError(err));
    } finally {
      setSending(false);
    }
  }

  return (
    <form onSubmit={handleInvite} className="p-6 space-y-4">
      <div className="flex flex-col gap-1">
        <label htmlFor={emailId} className={LABEL_CLASS}>invite by email</label>
        <div className="flex gap-2">
          <input id={emailId} type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="user@example.com" className={`${FIELD_INPUT_CLASS} flex-1`} autoComplete="off" />
          <RoleSelect value={role} onChange={setRole} disabled={sending} ariaLabel="invited member role" />
        </div>
      </div>
      <div role="alert" aria-live="assertive">{error && <p className={ERROR_CLASS}>{error}</p>}</div>
      <div role="status" aria-live="polite">{notice && <p className={NEUTRAL_CLASS}>{notice}</p>}</div>
      <PendingButton type="submit" pending={sending} pendingLabel="sending…" disabled={sending || !email.trim()}>
        send invitation
      </PendingButton>
    </form>
  );
}

export function TeamInvitationsSection({ org, perms }: TeamInvitationsSectionProps) {
  const { planTier } = useSubscription();
  const { invitations } = useOrganization({
    invitations: { pageSize: 20, keepPreviousData: true },
  });

  const { toast } = useToast();
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [demoTeam, setDemoTeam] = useState<boolean | null>(null);

  useEffect(() => {
    let active = true;
    void getConnections()
      .then((connections) => {
        if (active) setDemoTeam(connections.some((connection) => connection.tags?.includes("sp-demo")));
      })
      .catch(() => { if (active) setDemoTeam(false); });
    return () => { active = false; };
  }, [org.id]);

  const reverifiedRevoke = useReverification(
    (inv: OrganizationInvitationResource) => inv.revoke(),
  );

  async function handleRevoke(inv: OrganizationInvitationResource) {
    setError(null);
    setNotice(null);
    try {
      await reverifiedRevoke(inv);
      toast("invitation revoked", "success");
      invitations?.revalidate?.();
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
  // Only show skeleton on initial load, not on background refetches
  const showSkeleton = isLoading && data.length === 0;
  const freeCapacityFull = planTier === "free" && (org.membersCount ?? 0) + data.length >= 2;

  return (
    <section className="mb-8">
      <SectionHeader icon={Mail} title="invitations" />
      <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)]">
        {/* Invite form — admin only */}
        {perms.canInvite && demoTeam === false && !freeCapacityFull && (
          <div className="border-b border-[var(--color-border)]">
            <TeamInvitationForm org={org} onInvited={() => invitations?.revalidate?.()} />
          </div>
        )}

        {perms.canInvite && demoTeam === false && freeCapacityFull && (
          <p className="border-b border-[var(--color-border)] px-6 py-4 text-xs text-[var(--color-text-muted)]">
            The free plan includes the owner plus one active or pending teammate.
          </p>
        )}

        {demoTeam && (
          <p className="border-b border-[var(--color-border)] px-6 py-4 text-xs text-[var(--color-text-muted)]">
            Demo Teams are personal. Start “Connect my data” from Getting Started to create a Team for collaboration.
          </p>
        )}

        <div role="alert" aria-live="assertive" aria-atomic="true" className="px-4">
          {error && <p className={`${ERROR_CLASS} pt-3`}>{error}</p>}
        </div>
        <div role="status" aria-live="polite" aria-atomic="true" className="px-4">
          {notice && <p className={`${NEUTRAL_CLASS} pt-3`}>{notice}</p>}
        </div>

        {/* Pending invitations list */}
        {showSkeleton ? (
          <InvitationListSkeleton rows={2} />
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
            <PendingButton
              size="sm"
              variant="secondary"
              pending={isLoading}
              onClick={() => invitations?.fetchNext?.()}
            >
              load more
            </PendingButton>
          </div>
        )}
      </div>
    </section>
  );
}
