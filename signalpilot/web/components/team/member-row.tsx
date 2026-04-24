"use client";

/**
 * Single row in the members list.
 * Columns: avatar, name/email, role pill, admin actions.
 */

import type { OrganizationMembershipResource } from "@clerk/types";
import { Loader2 } from "lucide-react";
import { InitialsAvatar } from "./initials-avatar";
import { RoleSelect } from "./role-select";
import { PendingButton } from "@/components/ui/pending-button";
import { roleLabel, type TeamRole } from "@/lib/team/roles";
import type { TeamPermissions } from "@/lib/team/use-team-permissions";
import { NEUTRAL_CLASS } from "@/components/auth/auth-primitives";

export interface MemberRowProps {
  membership: OrganizationMembershipResource;
  isSelf: boolean;
  perms: TeamPermissions;
  onRoleChange: (userId: string, role: TeamRole) => Promise<void>;
  onRemove: (membership: OrganizationMembershipResource) => void;
  updatingUserId: string | null;
}

export function MemberRow({
  membership,
  isSelf,
  perms,
  onRoleChange,
  onRemove,
  updatingUserId,
}: MemberRowProps) {
  const { publicUserData, role } = membership;
  const displayName =
    [publicUserData?.firstName, publicUserData?.lastName].filter(Boolean).join(" ") ||
    publicUserData?.identifier ||
    "—";
  const email = publicUserData?.identifier ?? "—";
  const imageUrl = publicUserData?.imageUrl;
  const userId = publicUserData?.userId;
  const isUpdating = updatingUserId === userId;

  return (
    <div className="flex items-center gap-3 py-2.5 px-4 border-b border-[var(--color-border)] last:border-b-0">
      {/* Avatar */}
      <InitialsAvatar name={displayName} imageUrl={imageUrl} size={28} />

      {/* Name + email */}
      <div className="flex-1 min-w-0">
        <p
          className="text-[13px] text-[var(--color-text)] font-mono truncate"
          title={displayName}
        >
          {displayName}
          {isSelf && (
            <span className={`ml-2 ${NEUTRAL_CLASS}`}>(you)</span>
          )}
        </p>
        <p
          className="text-[11px] text-[var(--color-text-dim)] font-mono truncate"
          title={email}
        >
          {email}
        </p>
      </div>

      {/* Role area */}
      <div className="flex items-center gap-2 flex-shrink-0">
        {!isSelf && perms.canUpdate && userId ? (
          <>
            <RoleSelect
              value={role as TeamRole}
              onChange={(next) => onRoleChange(userId, next)}
              disabled={isUpdating}
              ariaLabel={`change role for ${displayName}`}
            />
            {isUpdating && (
              <span className={`${NEUTRAL_CLASS} flex items-center gap-1`} aria-live="polite">
                <Loader2 className="w-3 h-3 animate-spin" />
                saving
              </span>
            )}
          </>
        ) : (
          <span className="px-2 py-0.5 text-[11px] font-mono tracking-wider border border-[var(--color-border)] text-[var(--color-text-dim)]">
            {roleLabel(role)}
          </span>
        )}

        {/* Remove button — hidden for self */}
        {!isSelf && perms.canRemove && (
          <PendingButton
            size="sm"
            variant="danger"
            pending={false}
            onClick={() => onRemove(membership)}
            aria-label={`remove ${displayName} from team`}
          >
            remove
          </PendingButton>
        )}
      </div>
    </div>
  );
}
