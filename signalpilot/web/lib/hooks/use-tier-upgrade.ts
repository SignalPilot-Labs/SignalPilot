"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTierBranding } from "@/lib/hooks/use-tier-branding";
import type { BrandTier } from "@/lib/tier-branding";

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
    // localStorage unavailable (private mode, quota) — user may see celebration
    // twice across sessions; not a correctness bug.
  }
}

interface TierUpgradeState {
  celebratingTier: BrandTier | null;
  dismiss: () => void;
}

export function useTierUpgrade(): TierUpgradeState {
  const branding = useTierBranding();

  // Lazy initializer is PURE — null-case write happens in the effect below so
  // first-mount writes don't run during render.
  const [lastSeen] = useState<BrandTier | null>(() => readStorage());

  const [celebratingTier, setCelebratingTier] = useState<BrandTier | null>(null);

  const comparedRef = useRef(false);

  // Capture primitives so dismiss is stable across new branding object identities.
  const brandingEnabled = branding.enabled;
  const brandingTier = branding.enabled ? branding.tier : ("free" as BrandTier);

  const dismiss = useCallback(() => {
    if (brandingEnabled) {
      writeStorage(brandingTier);
    }
    setCelebratingTier(null);
  }, [brandingEnabled, brandingTier]);

  // comparedRef must NOT latch before enabled — if subscription loads after
  // first render (e.g. Stripe webhook), the effect must still fire once ready.
  useEffect(() => {
    if (!branding.enabled) return;
    if (comparedRef.current) return;
    comparedRef.current = true;

    const current = branding.tier;

    if (lastSeen === null) {
      writeStorage(current);
      return;
    }

    if (TIER_RANK[current] > TIER_RANK[lastSeen]) {
      setCelebratingTier(current);
    }
  }, [branding, lastSeen]);

  useEffect(() => {
    if (!branding.enabled) return;

    function handleStorageEvent(e: StorageEvent) {
      if (e.key !== STORAGE_KEY) return;
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
