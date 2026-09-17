"use client";

import { useCallback, useMemo } from "react";
import { useAppAuth } from "~/lib/auth-context";
import { useSubscription } from "~/lib/subscription-context";
import { LOCAL_PERMISSIONS, type OrgRole, type Permission } from "~/lib/permissions";

export interface UsePermissions {
  role: OrgRole;
  isAdmin: boolean;
  /** True when the caller holds the permission. Unknown permissions are false. */
  can: (permission: Permission) => boolean;
  /** False until the server has answered; render read-only, not a flash of admin controls. */
  loaded: boolean;
}

/**
 * The one hook every gated control reads. Sourced from `GET /api/me` through
 * the subscription context; local mode is admin with every permission.
 */
export function usePermissions(): UsePermissions {
  const { isCloudMode } = useAppAuth();
  const { permissions: cloud } = useSubscription();
  const set = isCloudMode ? cloud : LOCAL_PERMISSIONS;
  const can = useCallback((permission: Permission) => set.permissions.has(permission), [set]);
  return useMemo(
    () => ({ role: set.role, isAdmin: set.isAdmin, can, loaded: set.loaded }),
    [set, can],
  );
}
