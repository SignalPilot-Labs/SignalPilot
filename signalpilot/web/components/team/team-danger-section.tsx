"use client";

/**
 * Danger zone: Leave team (all members) + Delete team (admin only).
 * Both require ConfirmDialog + useReverification.
 * Delete requires typed team name confirmation.
 * Sequence for both: reverify → setActive(null) → router.push("/onboarding")
 */

import React, { useState } from "react";
import { AlertTriangle, Loader2 } from "lucide-react";
import { useReverification, useClerk } from "@clerk/nextjs";
import { useRouter } from "next/navigation";
import type { OrganizationResource, DeletedObjectResource } from "@clerk/types";
import { SectionHeader } from "@/components/ui/section-header";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  FIELD_INPUT_CLASS,
  LABEL_CLASS,
  ERROR_CLASS,
  NEUTRAL_CLASS,
} from "@/components/auth/auth-primitives";
import { isReverificationCancelledError } from "@/lib/security/use-reverify";
import { formatClerkError } from "@/lib/security/clerk-errors";
import type { TeamPermissions } from "@/lib/team/use-team-permissions";

interface LeaveOrganizationUser {
  leaveOrganization: (organizationId: string) => Promise<DeletedObjectResource>;
}

export interface TeamDangerSectionProps {
  org: OrganizationResource;
  perms: TeamPermissions;
  user: LeaveOrganizationUser;
}

export function TeamDangerSection({ org, perms, user }: TeamDangerSectionProps) {
  const router = useRouter();
  const { setActive } = useClerk();

  // Leave team
  const [leaveConfirmOpen, setLeaveConfirmOpen] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const [leaveError, setLeaveError] = useState<string | null>(null);
  const [leaveNotice, setLeaveNotice] = useState<string | null>(null);

  // Delete team
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [deleteNotice, setDeleteNotice] = useState<string | null>(null);
  const [typedName, setTypedName] = useState("");

  const deleteEnabled =
    org.adminDeleteEnabled !== false; // undefined → treat as enabled

  const reverifiedLeave = useReverification(
    (id: string): Promise<DeletedObjectResource> => user.leaveOrganization(id),
  );

  const reverifiedDelete = useReverification(
    (): Promise<void> => org.destroy(),
  );

  async function handleLeaveConfirm() {
    setLeaveConfirmOpen(false);
    setLeaving(true);
    setLeaveError(null);
    setLeaveNotice(null);
    try {
      await reverifiedLeave(org.id);
      await setActive({ organization: null });
      router.push("/onboarding");
    } catch (err) {
      if (isReverificationCancelledError(err)) {
        setLeaveNotice("reverification required to leave team");
      } else {
        setLeaveError(formatClerkError(err));
      }
      setLeaving(false);
    }
  }

  async function handleDeleteConfirm() {
    setDeleteConfirmOpen(false);
    setDeleting(true);
    setDeleteError(null);
    setDeleteNotice(null);
    try {
      await reverifiedDelete();
      await setActive({ organization: null });
      router.push("/onboarding");
    } catch (err) {
      if (isReverificationCancelledError(err)) {
        setDeleteNotice("reverification required to delete team");
      } else {
        setDeleteError(formatClerkError(err));
      }
      setDeleting(false);
    }
  }

  const dangerBtnClass =
    "px-5 py-2.5 bg-[var(--color-error)] text-white text-[12px] uppercase tracking-wider hover:opacity-90 transition-opacity disabled:opacity-40 font-mono focus:outline-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-error)] focus-visible:ring-offset-1 focus-visible:ring-offset-[var(--color-bg-card)]";

  return (
    <section className="mb-8">
      <SectionHeader icon={AlertTriangle} title="danger zone" iconColor="text-[var(--color-error)]" />
      <div className="border border-[var(--color-error)]/30 bg-[var(--color-bg-card)] divide-y divide-[var(--color-border)]">

        {/* Leave team — all members */}
        <div className="p-6 space-y-3">
          <p className={LABEL_CLASS}>leave team</p>
          <p className="text-[12px] text-[var(--color-text-muted)] tracking-wider leading-relaxed">
            Leaving will revoke your access to {org.name}. You can be re-invited by an admin.
          </p>
          <div role="alert" aria-live="assertive" aria-atomic="true">
            {leaveError && <p className={ERROR_CLASS}>{leaveError}</p>}
          </div>
          <div role="status" aria-live="polite" aria-atomic="true">
            {leaveNotice && <p className={NEUTRAL_CLASS}>{leaveNotice}</p>}
          </div>
          <button
            type="button"
            onClick={() => setLeaveConfirmOpen(true)}
            disabled={leaving}
            className={dangerBtnClass}
          >
            {leaving ? <Loader2 className="w-3.5 h-3.5 animate-spin inline mr-2" /> : null}
            leave team
          </button>
        </div>

        {/* Delete team — admin only */}
        {perms.canDelete && (
          <div className="p-6 space-y-3">
            <p className={LABEL_CLASS}>delete team</p>
            <p className="text-[12px] text-[var(--color-text-muted)] tracking-wider leading-relaxed">
              This permanently deletes {org.name}, revokes all members, and cannot be undone.
            </p>

            {/* Typed confirmation */}
            <div className="flex flex-col gap-1">
              <label htmlFor="delete-confirm-name" className={LABEL_CLASS}>
                type <span className="text-[var(--color-text)]">{org.name}</span> to confirm
              </label>
              <input
                id="delete-confirm-name"
                type="text"
                value={typedName}
                onChange={(e) => setTypedName(e.target.value)}
                placeholder={org.name}
                className={FIELD_INPUT_CLASS}
                autoComplete="off"
              />
            </div>

            <div role="alert" aria-live="assertive" aria-atomic="true">
              {deleteError && <p className={ERROR_CLASS}>{deleteError}</p>}
            </div>
            <div role="status" aria-live="polite" aria-atomic="true">
              {deleteNotice && <p className={NEUTRAL_CLASS}>{deleteNotice}</p>}
            </div>

            {!deleteEnabled && (
              <p className={NEUTRAL_CLASS}>Admin delete is disabled for this instance.</p>
            )}

            <button
              type="button"
              onClick={() => setDeleteConfirmOpen(true)}
              disabled={deleting || typedName !== org.name || !deleteEnabled}
              className={dangerBtnClass}
            >
              {deleting ? <Loader2 className="w-3.5 h-3.5 animate-spin inline mr-2" /> : null}
              delete team
            </button>
          </div>
        )}
      </div>

      <ConfirmDialog
        open={leaveConfirmOpen}
        title="leave team"
        message={`Leave ${org.name}? You will lose access immediately. An admin can re-invite you.`}
        confirmLabel="leave"
        cancelLabel="cancel"
        variant="danger"
        onConfirm={handleLeaveConfirm}
        onCancel={() => setLeaveConfirmOpen(false)}
      />

      <ConfirmDialog
        open={deleteConfirmOpen}
        title="delete team"
        message={`Delete ${org.name}? this cannot be undone.`}
        confirmLabel="delete"
        cancelLabel="cancel"
        variant="danger"
        onConfirm={handleDeleteConfirm}
        onCancel={() => setDeleteConfirmOpen(false)}
      />
    </section>
  );
}
