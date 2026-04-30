"use client";

/**
 * Derives permissions from the active organization membership role.
 * All permissions are role-based for R3.
 * TODO (R5): Switch to membership.permissions[] granular checks when
 * custom role split-permission support is needed.
 */

import { useOrganization } from "@clerk/nextjs";
import { isAdminRole } from "./roles";

export interface TeamPermissions {
  isAdmin: boolean;
  canInvite: boolean;
  canRemove: boolean;
  canUpdate: boolean;
  canDelete: boolean;
}

export function useTeamPermissions(): TeamPermissions {
  const { membership } = useOrganization();
  const isAdmin = isAdminRole(membership?.role);
  return {
    isAdmin,
    canInvite: isAdmin,
    canRemove: isAdmin,
    canUpdate: isAdmin,
    canDelete: isAdmin,
  };
}
