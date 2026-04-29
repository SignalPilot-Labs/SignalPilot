"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTierBranding } from "@/lib/hooks/use-tier-branding";
import type { BrandTier } from "@/lib/tier-branding";

// Follow repo convention: sp_ prefix + snake_case (sp_api_key, sp_query_history, etc.)
const STORAGE_KEY = "sp_tier_last_seen";

const TIER_RANK: Record<BrandTier, number> = {
  free: 0,
  pro: 1,
  team: 2,
  enterprise: 3,
};

function readStorage(): BrandTier | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw && raw in TIER_RANK) return raw as BrandTier;
    return null;
  } catch {
    return null;
  }
}

function writeStorage(tier: BrandTier): void {
  try {
    localStorage.setItem(STORAGE_KEY, tier);
  } catch {
    // localStorage unavailable (private mode, quota) — acceptable, user may see
    // celebration twice across sessions, not a correctness bug.
  }
}

export interface TierUpgradeState {
  celebratingTier: BrandTier | null;
  dismiss: () => void;
}

export function useTierUpgrade(): TierUpgradeState {
  // Hooks are always called unconditionally — early returns are by state, not
  // by short-circuiting before hook calls.
  const branding = useTierBranding();

  // Lazy initializer reads from storage only on the client (SSR-safe).
  // NOTE: the initializer is PURE — it does NOT write to storage.
  // The null-case write happens in the useEffect below (spec-reviewer fix #2).
  const [lastSeen] = useState<BrandTier | null>(() => readStorage());

  const [celebratingTier, setCelebratingTier] = useState<BrandTier | null>(null);

  // Tracks whether the effect has fired so we only run the comparison once.
  const comparedRef = useRef(false);

  // Capture primitive deps so dismiss doesn't re-create on every branding object
  // reference change (useTierBranding returns a new object each render).
  const brandingEnabled = branding.enabled;
  const brandingTier = branding.enabled ? branding.tier : ("free" as BrandTier);

  const dismiss = useCallback(() => {
    if (brandingEnabled) {
      writeStorage(brandingTier);
    }
    setCelebratingTier(null);
  }, [brandingEnabled, brandingTier]);

  // One-shot effect: compare lastSeen vs current tier and decide whether to celebrate.
  // comparedRef must NOT latch before enabled — if cloud subscription loads after
  // first render (e.g. Stripe webhook), the ref must still be clear so this effect
  // runs once branding is ready.
  useEffect(() => {
    if (!branding.enabled) return;
    if (comparedRef.current) return;
    comparedRef.current = true;

    const current = branding.tier;

    if (lastSeen === null) {
      // First-ever mount for this user: silently record; no celebration.
      writeStorage(current);
      return;
    }

    const lastRank = TIER_RANK[lastSeen];
    const currentRank = TIER_RANK[current];

    if (currentRank > lastRank) {
      // Upgrade detected — celebrate! Storage is written only when dismissed.
      setCelebratingTier(current);
    }
    // Same rank or downgrade: no-op (no celebration, no storage write needed).
  }, [branding, lastSeen]);

  // Cross-tab safety: if another tab dismisses (writes storage), clear here too.
  useEffect(() => {
    if (!branding.enabled) return;

    function handleStorageEvent(e: StorageEvent) {
      if (e.key !== STORAGE_KEY) return;
      // Another tab wrote the key — treat as dismiss in this tab.
      setCelebratingTier(null);
    }

    window.addEventListener("storage", handleStorageEvent);
    return () => window.removeEventListener("storage", handleStorageEvent);
  }, [branding.enabled]);

  if (!branding.enabled) {
    return { celebratingTier: null, dismiss: () => {} };
  }

  return { celebratingTier, dismiss };
}
