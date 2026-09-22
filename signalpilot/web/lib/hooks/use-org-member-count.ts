"use client";

import { useOrganization } from "@clerk/nextjs";

/**
 * Members of the active Clerk organization, as the billing dialog counts
 * seats. Returns null until Clerk has loaded or when no organization is
 * active. Cloud mode only: the caller must sit under ClerkProvider (the
 * billing page already gates on `isCloudMode`); local mode has no Clerk and
 * treats the count as unknown.
 */
export function useOrgMemberCount(): number | null {
  const { organization, isLoaded } = useOrganization();
  if (!isLoaded || !organization) return null;
  const n = organization.membersCount;
  return typeof n === "number" && Number.isFinite(n) ? n : null;
}
