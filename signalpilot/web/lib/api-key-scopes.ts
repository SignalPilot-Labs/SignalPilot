export const ALL_SCOPES: { value: string; label: string; description: string }[] = [
  { value: "read", label: "read", description: "read-only access to data" },
  { value: "query", label: "query", description: "execute governed sql queries" },
  { value: "write", label: "write", description: "write and modify data" },
  { value: "admin", label: "admin", description: "full administrative access" },
];
