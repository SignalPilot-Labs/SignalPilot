// Permission vocabulary for org admin / member gating.
//
// Mirrors gateway/auth/permissions.py. The gateway reports a role and a list
// of permissions on GET /api/me and on the chat bootstrap; the web only ever
// decides what to show or disable from that list. The server enforces.

export type OrgRole = "admin" | "member";

export const ADMIN_PERMISSIONS = [
  "connections.write",
  "connections.test_credentials",
  "schema.curate",
  "settings.write",
  "secrets.org.write",
  "byok.manage",
  "keys.admin",
  "knowledge.publish",
  "reports.manage",
  "evals.run",
  "improvements.run",
  "schema_watches.write",
  "projects.write",
  "github.write",
  "chat.default_project",
  "budgets.write",
  "audit.read",
  "billing.manage",
  "usage.org",
  "team.manage",
  "integrations.write",
  "mcp.org_connectors",
  "security.read",
  "branch.production_write",
  // member-level
  "keys.personal",
  "knowledge.propose",
  "usage.self",
] as const;

export type Permission = (typeof ADMIN_PERMISSIONS)[number];

/** What a member holds when the server has not said otherwise. */
export const MEMBER_PERMISSIONS: readonly Permission[] = [
  "keys.personal",
  "knowledge.propose",
  "usage.self",
];

/** API key scopes a member may put on a personal key (brief, decision 1). */
export const MEMBER_KEY_SCOPES: readonly string[] = ["read", "query", "execute"];

/** The resolved permission set the UI gates on. */
export interface PermissionSet {
  role: OrgRole;
  isAdmin: boolean;
  permissions: ReadonlySet<string>;
  /** False until a server answer (or the local-mode default) is in hand. */
  loaded: boolean;
}

/** Any server payload that carries a role: `/api/me` or the chat bootstrap. */
export interface RolePayload {
  role?: string | null;
  is_admin?: boolean | null;
  permissions?: string[] | null;
}

export const LOCAL_PERMISSIONS: PermissionSet = Object.freeze({
  role: "admin",
  isAdmin: true,
  permissions: new Set<string>(ADMIN_PERMISSIONS),
  loaded: true,
});

/** The fallback for a signed-in cloud user before the server has answered. */
export const UNLOADED_MEMBER_PERMISSIONS: PermissionSet = Object.freeze({
  role: "member",
  isAdmin: false,
  permissions: new Set<string>(MEMBER_PERMISSIONS),
  loaded: false,
});

function roleOf(payload: RolePayload): OrgRole {
  if (payload.role === "admin" || payload.role === "member") return payload.role;
  return payload.is_admin ? "admin" : "member";
}

/**
 * Build the permission set from a server payload. A payload without a
 * `permissions` list (an older gateway) falls back to the role's default set,
 * so a member never sees admin controls and an admin keeps them.
 */
export function permissionsFromPayload(payload: RolePayload | null | undefined): PermissionSet {
  if (!payload) return UNLOADED_MEMBER_PERMISSIONS;
  const role = roleOf(payload);
  const listed = Array.isArray(payload.permissions) ? payload.permissions : null;
  const permissions = listed
    ? new Set(listed)
    : new Set<string>(role === "admin" ? ADMIN_PERMISSIONS : MEMBER_PERMISSIONS);
  return { role, isAdmin: role === "admin", permissions, loaded: true };
}

/** True when the payload carries something the UI can gate on. */
export function payloadHasRole(payload: RolePayload | null | undefined): boolean {
  if (!payload) return false;
  return (
    payload.role === "admin" ||
    payload.role === "member" ||
    typeof payload.is_admin === "boolean" ||
    Array.isArray(payload.permissions)
  );
}
