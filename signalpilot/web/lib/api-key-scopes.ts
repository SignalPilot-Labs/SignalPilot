export const ALL_SCOPES: { value: string; label: string; description: string }[] = [
  { value: "read", label: "read", description: "read-only access to data" },
  { value: "query", label: "query", description: "execute governed sql queries" },
  { value: "execute", label: "execute", description: "execute notebook code and project commands" },
  { value: "write", label: "write", description: "modify workspace content and resources; sql governance still applies" },
  { value: "dbt_proxy", label: "dbt_proxy", description: "run dbt through the governed database proxy" },
  { value: "agent:run", label: "agent:run", description: "launch, continue, and manage cloud agents; up to 2 active agents per account" },
  { value: "admin", label: "admin", description: "full administrative access" },
];

/** Scopes a member may put on a personal key; admins may use every scope. */
export const MEMBER_SCOPES: readonly string[] = ["read", "query", "execute"];

/** The scope options to offer, by whether the caller holds `keys.admin`. */
export function scopesForCaller(canAdminKeys: boolean): typeof ALL_SCOPES {
  if (canAdminKeys) return ALL_SCOPES;
  return ALL_SCOPES.filter((s) => MEMBER_SCOPES.includes(s.value));
}
