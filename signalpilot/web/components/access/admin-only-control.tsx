"use client";

import type { ReactNode } from "react";
import { Tooltip } from "~/components/ui/tooltip";
import { usePermissions } from "~/lib/hooks/use-permissions";
import type { Permission } from "~/lib/permissions";

export const ADMIN_ONLY_TOOLTIP = "Only org admins can change this";

/**
 * Wraps a control that changes an org-level value. Admins get the control as
 * is; everyone else gets it disabled with the one tooltip that teaches the
 * rule. Native form controls inside are disabled through a `fieldset`, so
 * buttons and inputs need no per-element `disabled` prop.
 */
export function AdminOnlyControl({
  permission,
  allowed,
  children,
  position = "top",
  className,
}: {
  /** The permission that unlocks the control. */
  permission: Permission;
  /** Overrides the hook, for surfaces that already computed the answer. */
  allowed?: boolean;
  children: ReactNode;
  position?: "top" | "bottom" | "left" | "right";
  className?: string;
}) {
  const { can } = usePermissions();
  const ok = allowed ?? can(permission);
  if (ok) return <>{children}</>;
  return (
    <Tooltip content={ADMIN_ONLY_TOOLTIP} position={position}>
      <fieldset
        disabled
        aria-disabled="true"
        data-testid="admin-only-control"
        className={`m-0 p-0 border-0 min-w-0 opacity-50 cursor-not-allowed [&>*]:pointer-events-none ${className ?? ""}`}
      >
        {children}
      </fieldset>
    </Tooltip>
  );
}
