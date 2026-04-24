"use client";

/**
 * Single row for a pending organization invitation.
 * Columns: email, role pill, invited-at, revoke button.
 */

import { useState } from "react";
import type { OrganizationInvitationResource } from "@clerk/types";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { PendingButton } from "@/components/ui/pending-button";
import { roleLabel } from "@/lib/team/roles";
import { NEUTRAL_CLASS } from "@/components/auth/auth-primitives";

export interface InvitationRowProps {
  invitation: OrganizationInvitationResource;
  canRevoke: boolean;
  onRevoke: (invitation: OrganizationInvitationResource) => Promise<void>;
}

function relativeTime(date: Date): string {
  const diffMs = Date.now() - date.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  const diffHour = Math.floor(diffMin / 60);
  const diffDay = Math.floor(diffHour / 24);
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  if (diffHour < 24) return `${diffHour}h ago`;
  return `${diffDay}d ago`;
}

export function InvitationRow({ invitation, canRevoke, onRevoke }: InvitationRowProps) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [revoking, setRevoking] = useState(false);

  async function handleConfirm() {
    setConfirmOpen(false);
    setRevoking(true);
    try {
      await onRevoke(invitation);
    } finally {
      setRevoking(false);
    }
  }

  return (
    <>
      <div className="flex items-center gap-3 py-2.5 px-4 border-b border-[var(--color-border)] last:border-b-0">
        {/* Email */}
        <p
          className="flex-1 text-[13px] text-[var(--color-text)] font-mono truncate"
          title={invitation.emailAddress}
        >
          {invitation.emailAddress}
        </p>

        {/* Role pill */}
        <span className="px-2 py-0.5 text-[11px] font-mono tracking-wider border border-[var(--color-border)] text-[var(--color-text-dim)] flex-shrink-0">
          {roleLabel(invitation.role)}
        </span>

        {/* Invited at */}
        <span className={`${NEUTRAL_CLASS} flex-shrink-0 tabular-nums`}>
          invited {relativeTime(invitation.createdAt)}
        </span>

        {/* Revoke button */}
        {canRevoke && (
          <PendingButton
            size="sm"
            variant="danger"
            pending={revoking}
            onClick={() => setConfirmOpen(true)}
            aria-label={`revoke invitation to ${invitation.emailAddress}`}
          >
            revoke
          </PendingButton>
        )}
      </div>

      <ConfirmDialog
        open={confirmOpen}
        title="revoke invitation"
        message={`Revoke invitation to ${invitation.emailAddress}? They will no longer be able to join via this invitation.`}
        confirmLabel="revoke"
        cancelLabel="cancel"
        variant="danger"
        onConfirm={handleConfirm}
        onCancel={() => setConfirmOpen(false)}
      />
    </>
  );
}
