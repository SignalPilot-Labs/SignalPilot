/**
 * Deterministic mock usage data generation for cloud API key analytics.
 * Pure functions — no React, no hooks, no external dependencies.
 */

import type { ApiKeyResponse } from "@/lib/backend-client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface DailyUsagePoint {
  date: string;
  requests: number;
}

export interface KeyUsageStats {
  keyId: string;
  keyName: string;
  totalRequests: number;
  last7Days: number;
  lastUsedAt: string;
}

export interface RateLimitInfo {
  limit: number;
  used: number;
  resetAt: string;
  percentage: number;
}

// ---------------------------------------------------------------------------
// Seeded PRNG — mulberry32
// ---------------------------------------------------------------------------

/**
 * Mulberry32 seeded PRNG. Returns a function that yields numbers in [0, 1).
 */
function mulberry32(seed: number): () => number {
  let s = seed;
  return function () {
    s += 0x6d2b79f5;
    let z = s;
    z = ((z ^ (z >>> 15)) * (z | 1)) >>> 0;
    z ^= z + ((z ^ (z >>> 7)) * (z | 61)) >>> 0;
    return ((z ^ (z >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * Derive a numeric seed from a UUID string. Uses a simple djb2-style hash.
 */
function seedFromUUID(uuid: string): number {
  let hash = 5381;
  for (let i = 0; i < uuid.length; i++) {
    hash = ((hash << 5) + hash + uuid.charCodeAt(i)) >>> 0;
  }
  return hash;
}

/**
 * Returns 1.0 for weekdays, 0.35 for weekends (Saturday/Sunday).
 */
function weekdayMultiplier(date: Date): number {
  const day = date.getDay(); // 0 = Sun, 6 = Sat
  return day === 0 || day === 6 ? 0.35 : 1.0;
}

// ---------------------------------------------------------------------------
// generateDailyUsage
// ---------------------------------------------------------------------------

/**
 * Returns `{ date, requests }[]` for the last `days` days.
 * Seeded from key IDs for stable, deterministic output across renders.
 * Applies weekday patterns and a gentle upward trend.
 */
export function generateDailyUsage(
  keys: ApiKeyResponse[],
  days: number,
): DailyUsagePoint[] {
  if (keys.length === 0) {
    // No keys — return zeroed array
    const result: DailyUsagePoint[] = [];
    for (let i = days - 1; i >= 0; i--) {
      const d = new Date();
      d.setDate(d.getDate() - i);
      const month = d.getMonth() + 1;
      const day = d.getDate();
      result.push({ date: `${month}/${day}`, requests: 0 });
    }
    return result;
  }

  // Combine seeds from all key IDs for a stable aggregate seed
  const combinedSeed = keys.reduce(
    (acc, k) => (acc ^ seedFromUUID(k.id)) >>> 0,
    0x12345678,
  );
  const rand = mulberry32(combinedSeed);

  const result: DailyUsagePoint[] = [];
  const basePerKey = 50; // min requests per key per day
  const rangePerKey = 250; // range above base (50-300 per key)

  for (let i = days - 1; i >= 0; i--) {
    const d = new Date();
    d.setDate(d.getDate() - i);

    const month = d.getMonth() + 1;
    const day = d.getDate();
    const dateStr = `${month}/${day}`;

    // Gentle upward trend: days further back get slightly lower multiplier
    const trendMultiplier = 0.75 + (0.25 * (days - i)) / days;

    const wdm = weekdayMultiplier(d);
    const rawPerKey = basePerKey + rand() * rangePerKey;
    const requests = Math.round(
      rawPerKey * keys.length * wdm * trendMultiplier,
    );

    result.push({ date: dateStr, requests: Math.max(0, requests) });
  }

  return result;
}

// ---------------------------------------------------------------------------
// generateKeyUsage
// ---------------------------------------------------------------------------

/**
 * Returns usage stats for a single key, seeded from key.id for stability.
 * Older keys (earlier created_at) have higher usage totals.
 */
export function generateKeyUsage(key: ApiKeyResponse): KeyUsageStats {
  const rand = mulberry32(seedFromUUID(key.id));

  // Age factor: keys created earlier get more total requests
  const createdMs = new Date(key.created_at).getTime();
  const nowMs = Date.now();
  const ageMs = Math.max(0, nowMs - createdMs);
  const ageDays = ageMs / (1000 * 60 * 60 * 24);

  // totalRequests: scale with age (1-30 days range), base 500-5000
  const ageFactor = Math.min(ageDays / 30, 1); // 0-1 over first 30 days
  const totalBase = 500 + ageFactor * 4500;
  const totalRequests = Math.round(totalBase + rand() * totalBase * 0.5);

  // last7Days: ~10-30% of total
  const last7Days = Math.round(totalRequests * (0.1 + rand() * 0.2));

  // lastUsedAt: within the last 24h for active keys
  const hoursAgo = Math.round(rand() * 23);
  const lastUsed = new Date(nowMs - hoursAgo * 60 * 60 * 1000);
  const lastUsedAt = lastUsed.toISOString();

  return {
    keyId: key.id,
    keyName: key.name,
    totalRequests,
    last7Days,
    lastUsedAt,
  };
}

// ---------------------------------------------------------------------------
// getRateLimitStatus
// ---------------------------------------------------------------------------

const PLAN_LIMITS: Record<string, number> = {
  free: 1000,
  pro: 10000,
  team: 100000,
};

/**
 * Returns rate limit status for the given plan tier.
 * Pass `planTier` from `useSubscription()` (camelCase, already normalized).
 */
export function getRateLimitStatus(planTier: string): RateLimitInfo {
  const limit = PLAN_LIMITS[planTier] ?? PLAN_LIMITS.free;

  // Seed from plan tier name + current UTC date for daily stability
  const today = new Date();
  const dayStr = `${today.getUTCFullYear()}-${today.getUTCMonth()}-${today.getUTCDate()}`;
  const seed = seedFromUUID(`${planTier}-${dayStr}`);
  const rand = mulberry32(seed);

  // used: 20-75% of limit to avoid always hitting warning/error zones
  const usedFraction = 0.2 + rand() * 0.55;
  const used = Math.round(limit * usedFraction);
  const percentage = Math.round((used / limit) * 100);

  // Reset at midnight UTC
  const resetAt = new Date();
  resetAt.setUTCHours(24, 0, 0, 0);

  return {
    limit,
    used,
    resetAt: resetAt.toISOString(),
    percentage,
  };
}
