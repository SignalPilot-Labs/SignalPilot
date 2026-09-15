"use client";

import type { ReactNode } from "react";
import { AdminOnlyPage } from "~/components/access/admin-only-page";
import { usePermissions } from "~/lib/hooks/use-permissions";
import type { Permission } from "~/lib/permissions";

/**
 * Wraps a whole admin-only page. A caller without the permission gets the
 * `AdminOnlyPage` notice instead of the page body; while the server has not
 * answered yet the hook already reports member, so nothing admin-only flashes.
 */
export function AdminGate({
  permission,
  title,
  subtitle = "settings",
  what,
  backHref,
  backLabel,
  children,
}: {
  permission: Permission;
  title: string;
  subtitle?: string;
  what?: string;
  backHref?: string;
  backLabel?: string;
  children: ReactNode;
}) {
  const { can } = usePermissions();
  if (!can(permission)) {
    return (
      <AdminOnlyPage
        title={title}
        subtitle={subtitle}
        what={what}
        backHref={backHref}
        backLabel={backLabel}
      />
    );
  }
  return <>{children}</>;
}
