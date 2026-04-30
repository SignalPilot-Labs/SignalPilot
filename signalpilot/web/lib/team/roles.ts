/**
 * Single source of truth for Clerk organization role constants.
 * Clerk default role keys are org:admin / org:member.
 * If a tenant uses custom roles, this file is the single point of change.
 */

export const ROLE_ADMIN = "org:admin" as const;
export const ROLE_MEMBER = "org:member" as const;

export type TeamRole = typeof ROLE_ADMIN | typeof ROLE_MEMBER;

export const ROLE_OPTIONS: Array<{ value: TeamRole; label: string }> = [
  { value: ROLE_ADMIN, label: "admin" },
  { value: ROLE_MEMBER, label: "member" },
];

export function isAdminRole(role: string | null | undefined): boolean {
  return role === ROLE_ADMIN;
}

export function roleLabel(role: string): string {
  const match = ROLE_OPTIONS.find((o) => o.value === role);
  return match ? match.label : role;
}
