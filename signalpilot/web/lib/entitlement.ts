/**
 * Entitlement model shared by the subscription context and every plan gate in
 * the UI. Pure functions, no React.
 *
 * The one gating rule: a feature is available when the org is on a billable
 * plan. "Billable" is derived here from the subscription row exactly as the
 * gateway derives it, so the UI and the API agree by construction.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Plan tiers the backend can store. `unlimited` exists only in local mode. */
export type EntitlementTier = "free" | "team" | "scale" | "enterprise" | "unlimited";

export type BillingInterval = "month" | "year";

export interface Entitlement {
  tier: EntitlementTier;
  isBillable: boolean;
  includedSeats: number;
  includedModels: number;
  includedEvalRuns: number;
  includedCredits: number;
  managed: boolean;
  billingInterval: BillingInterval;
  enterpriseFlags: Record<string, unknown>;
}

/** What this deployment can run, independent of what the org may run. */
export interface DeploymentCapabilities {
  evals: boolean;
  sandbox: boolean;
}

/**
 * Snake-case entitlement object as carried by the gateway bootstrap and
 * `/api/plan` payloads (`OrgEntitlement.to_dict()`).
 */
export interface EntitlementPayload {
  org_id?: string;
  tier: string;
  status?: string;
  is_billable: boolean;
  included_seats: number;
  included_models: number;
  included_eval_runs: number;
  included_credits: number;
  managed: boolean;
  billing_interval?: string;
  enterprise_flags?: Record<string, unknown> | null;
  grace_until?: string | null;
}

/** The fields of the backend subscription row that decide billability. */
export interface BillableRowInput {
  plan_tier: string;
  status: string;
  grace_until?: string | null;
  is_billable?: boolean | null;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const TIERS: readonly EntitlementTier[] = [
  "free",
  "team",
  "scale",
  "enterprise",
  "unlimited",
];

/** Ordering used for upgrade/downgrade labels and the upgrade celebration. */
export const TIER_RANK: Record<EntitlementTier, number> = {
  free: 0,
  team: 1,
  scale: 2,
  enterprise: 3,
  unlimited: 4,
};

export const FREE_ENTITLEMENT: Entitlement = {
  tier: "free",
  isBillable: false,
  includedSeats: 0,
  includedModels: 0,
  includedEvalRuns: 0,
  includedCredits: 0,
  managed: false,
  billingInterval: "month",
  enterpriseFlags: {},
};

/** Local mode has no backend: everything is on and nothing is metered. */
export const LOCAL_ENTITLEMENT: Entitlement = {
  tier: "unlimited",
  isBillable: true,
  includedSeats: 0,
  includedModels: 0,
  includedEvalRuns: 0,
  includedCredits: 0,
  managed: false,
  billingInterval: "month",
  enterpriseFlags: {},
};

// ---------------------------------------------------------------------------
// Derivation
// ---------------------------------------------------------------------------

export function normalizeTier(value: string | null | undefined): EntitlementTier {
  return (TIERS as readonly string[]).includes(value ?? "")
    ? (value as EntitlementTier)
    : "free";
}

function normalizeInterval(value: string | null | undefined): BillingInterval {
  return value === "year" ? "year" : "month";
}

/**
 * Mirror of the gateway rule: status in (active, trialing), or past_due inside
 * the grace window, and the tier is not free. When the backend already sends
 * `is_billable` that value wins.
 */
export function isBillableRow(row: BillableRowInput, now: Date = new Date()): boolean {
  if (typeof row.is_billable === "boolean") return row.is_billable;
  const tier = normalizeTier(row.plan_tier);
  if (tier === "free") return false;
  if (row.status === "active" || row.status === "trialing") return true;
  if (row.status === "past_due" && row.grace_until) {
    const grace = new Date(row.grace_until).getTime();
    return Number.isFinite(grace) && now.getTime() < grace;
  }
  return false;
}

export interface SubscriptionRowInput extends BillableRowInput {
  included_seats?: number | null;
  included_models?: number | null;
  included_eval_runs?: number | null;
  included_credits?: number | null;
  managed?: boolean | null;
  billing_interval?: string | null;
  enterprise_flags?: Record<string, unknown> | null;
}

/** Build the entitlement the UI gates on from the backend subscription row. */
export function entitlementFromSubscription(
  row: SubscriptionRowInput,
  now: Date = new Date(),
): Entitlement {
  return {
    tier: normalizeTier(row.plan_tier),
    isBillable: isBillableRow(row, now),
    includedSeats: row.included_seats ?? 0,
    includedModels: row.included_models ?? 0,
    includedEvalRuns: row.included_eval_runs ?? 0,
    includedCredits: row.included_credits ?? 0,
    managed: row.managed ?? false,
    billingInterval: normalizeInterval(row.billing_interval),
    enterpriseFlags: row.enterprise_flags ?? {},
  };
}

/** Build the entitlement from the gateway bootstrap payload. */
export function entitlementFromPayload(payload: EntitlementPayload): Entitlement {
  return {
    tier: normalizeTier(payload.tier),
    isBillable: Boolean(payload.is_billable),
    includedSeats: payload.included_seats ?? 0,
    includedModels: payload.included_models ?? 0,
    includedEvalRuns: payload.included_eval_runs ?? 0,
    includedCredits: payload.included_credits ?? 0,
    managed: Boolean(payload.managed),
    billingInterval: normalizeInterval(payload.billing_interval),
    enterpriseFlags: payload.enterprise_flags ?? {},
  };
}

/** Human label for a tier. */
export function tierLabel(tier: EntitlementTier): string {
  switch (tier) {
    case "team":
      return "Team";
    case "scale":
      return "Scale";
    case "enterprise":
      return "Enterprise";
    case "unlimited":
      return "Unlimited";
    default:
      return "Free";
  }
}
