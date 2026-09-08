"use client";

// Who published a dashboard, as the gallery and header show it. The gateway
// sends an email or name when it has one cheaply and otherwise the raw user
// id; a raw id is never shown, it becomes "You" for the viewer's own
// dashboards and nothing for anyone else's.

import { useAppAuth } from "~/lib/auth-context";
import type { PublishedDashboard } from "~/lib/api/dashboards";

type Owner = Pick<PublishedDashboard, "created_by_label" | "created_by_user_id">;

/** True for Clerk-style ids the backend fell back to instead of a name. */
export function isRawUserId(label: string): boolean {
  return label.startsWith("user_");
}

/** The label to show, or null when nothing readable is available. */
export function ownerLabel(owner: Owner, currentUserId: string | null | undefined): string | null {
  const label = owner.created_by_label.trim();
  if (!label) return null;
  if (!isRawUserId(label)) return label;
  return currentUserId && (label === currentUserId || owner.created_by_user_id === currentUserId)
    ? "You"
    : null;
}

export function useOwnerLabel(owner: Owner): string | null {
  const { user } = useAppAuth();
  return ownerLabel(owner, user?.id ?? null);
}
