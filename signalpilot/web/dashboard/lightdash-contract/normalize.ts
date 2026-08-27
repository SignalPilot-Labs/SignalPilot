import type { DashboardDefinition } from "./types";
import { dashboardDefinitionSchema } from "./schema";

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value)
        .filter(([, item]) => item !== undefined)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, canonicalize(item)]),
    );
  }
  return value;
}

export function normalizeDashboardDefinition(input: unknown): DashboardDefinition {
  const definition = dashboardDefinitionSchema.parse(input);
  return canonicalize(definition) as DashboardDefinition;
}

export function canonicalDashboardJson(input: unknown): string {
  return JSON.stringify(normalizeDashboardDefinition(input));
}

export async function hashDashboardDefinition(input: unknown): Promise<string> {
  const bytes = new TextEncoder().encode(canonicalDashboardJson(input));
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}
