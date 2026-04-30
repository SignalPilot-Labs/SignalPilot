"use client";

/**
 * Paginated members list with role change + remove.
 * - Admin: RoleSelect per non-self row, remove button.
 * - Non-admin: read-only role pill.
 * - Self row: role-change and remove hidden.
 */

import React, { useState } from "react";
import { Users } from "lucide-react";
import { TeamMemberListSkeleton } from "@/components/ui/list-skeletons";
import { PendingButton } from "@/components/ui/pending-button";
import { useReverification, useOrganization } from "@clerk/nextjs";
import { useUser } from "@clerk/nextjs";
import type { OrganizationResource, OrganizationMembershipResource } from "@clerk/types";
import { SectionHeader } from "@/components/ui/section-header";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useToast } from "@/components/ui/toast";
import { ERROR_CLASS, NEUTRAL_CLASS } from "@/components/auth/auth-primitives";
import { isReverificationCancelledError } from "@/lib/security/use-reverify";
import { formatClerkError } from "@/lib/security/clerk-errors";
import type { TeamPermissions } from "@/lib/team/use-team-permissions";
import type { TeamRole } from "@/lib/team/roles";
import { MemberRow } from "./member-row";

export interface TeamMembersSectionProps {
  org: OrganizationResource;
  me: OrganizationMembershipResource | null | undefined;
  perms: TeamPermissions;
}

export function TeamMembersSection({ org, me, perms }: TeamMembersSectionProps) {
  const { user } = useUser();
  const { memberships } = useOrganization({
    memberships: { pageSize: 20, keepPreviousData: true },
  });

  const { toast } = useToast();
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [updatingUserId, setUpdatingUserId] = useState<string | null>(null);
  const [removeTarget, setRemoveTarget] = useState<OrganizationMembershipResource | null>(null);

  const reverifiedUpdateMember = useReverification(
    (params: { userId: string; role: string }) =>
      org.updateMember({ userId: params.userId, role: params.role }),
  );

  const reverifiedRemoveMember = useReverification(
    (userId: string) => org.removeMember(userId),
  );

  async function handleRoleChange(userId: string, role: TeamRole) {
    setError(null);
    setNotice(null);
    setUpdatingUserId(userId);
    try {
      await reverifiedUpdateMember({ userId, role });
      memberships?.revalidate?.();
      toast("role updated", "success");
    } catch (err) {
      if (isReverificationCancelledError(err)) {
        setNotice("reverification required to change role");
      } else {
        setError(formatClerkError(err));
      }
    } finally {
      setUpdatingUserId(null);
    }
  }

  async function handleRemoveConfirm() {
    if (!removeTarget) return;
    const userId = removeTarget.publicUserData?.userId;
    if (!userId) { setRemoveTarget(null); return; }
    setRemoveTarget(null);
    setError(null);
    setNotice(null);
    try {
      await reverifiedRemoveMember(userId);
      // Discard the returned deleted-membership; let Clerk hook revalidate
      memberships?.revalidate?.();
      toast("member removed", "success");
    } catch (err) {
      if (isReverificationCancelledError(err)) {
        setNotice("reverification required to remove member");
      } else {
        setError(formatClerkError(err));
      }
    }
  }

  const data = memberships?.data ?? [];
  const isLoading = memberships?.isLoading ?? false;
  const hasNextPage = memberships?.hasNextPage ?? false;

  return (
    <section className="mb-8">
      <SectionHeader icon={Users} title={`members${data.length > 0 ? ` (${data.length})` : ""}`} />
      <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)]">
        {/* Async feedback */}
        <div role="alert" aria-live="assertive" aria-atomic="true" className="px-4">
          {error && <p className={`${ERROR_CLASS} pt-3`}>{error}</p>}
        </div>
        <div role="status" aria-live="polite" aria-atomic="true" className="px-4">
          {notice && <p className={`${NEUTRAL_CLASS} pt-3`}>{notice}</p>}
        </div>

        {isLoading && data.length === 0 ? (
          <TeamMemberListSkeleton rows={3} />
        ) : data.length === 0 ? (
          <p className={`${NEUTRAL_CLASS} p-4`}>no other members yet. invite someone below.</p>
        ) : (
          <div aria-live="polite">
            {data.map((m) => (
              <MemberRow
                key={m.id}
                membership={m}
                isSelf={m.publicUserData?.userId === user?.id}
                perms={perms}
                onRoleChange={handleRoleChange}
                onRemove={setRemoveTarget}
                updatingUserId={updatingUserId}
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
              onClick={() => memberships?.fetchNext?.()}
            >
              load more
            </PendingButton>
          </div>
        )}
      </div>

      {/* Remove confirm dialog */}
      <ConfirmDialog
        open={removeTarget !== null}
        title="remove member"
        message={
          removeTarget
            ? `Remove ${
                [removeTarget.publicUserData?.firstName, removeTarget.publicUserData?.lastName]
                  .filter(Boolean)
                  .join(" ") || removeTarget.publicUserData?.identifier || "this member"
              } from ${org.name}? They will lose access immediately.`
            : ""
        }
        confirmLabel="remove"
        cancelLabel="cancel"
        variant="danger"
        onConfirm={handleRemoveConfirm}
        onCancel={() => setRemoveTarget(null)}
      />
    </section>
  );
}

