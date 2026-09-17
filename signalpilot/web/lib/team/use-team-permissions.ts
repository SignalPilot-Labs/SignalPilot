"use client";

/**
 * Team-page permissions, derived from the org permission set the gateway
 * reports (`usePermissions`). Clerk's own membership role is no longer read
 * here: one source decides for every page.
 */

import { usePermissions } from "~/lib/hooks/use-permissions";

export interface TeamPermissions {
  isAdmin: boolean;
  canInvite: boolean;
  canRemove: boolean;
  canUpdate: boolean;
  canDelete: boolean;
}

export function useTeamPermissions(): TeamPermissions {
  const { isAdmin, can } = usePermissions();
  const manage = can("team.manage");
  return {
    isAdmin,
    canInvite: manage,
    canRemove: manage,
    canUpdate: manage,
    canDelete: manage,
  };
}
