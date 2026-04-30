"use client";

import { useEffect } from "react";
import { useTierBranding } from "@/lib/hooks/use-tier-branding";

/**
 * Pure side-effect component. Returns null always. Sets document.title to
 * "[<Tier>] SignalPilot" for paid cloud tiers; restores "SignalPilot" on
 * unmount or when branding becomes disabled.
 *
 * NOTE: The reset value is the literal "SignalPilot" — this MUST match
 * metadata.title in app/layout.tsx. If that value ever changes, update
 * this constant too.
 *
 * Why a client effect and not metadata: metadata.title is server-rendered
 * and static per route. Tier is per-user, per-session, and dynamic. A
 * client component is the smallest correct solution.
 *
 * Effect deps: [b.enabled, b.tier, b.brand?.label] — explicit stable
 * primitives, not the b object (referential instability would re-fire
 * on every render).
 */

const CANONICAL_TITLE = "SignalPilot";

export function TabTitle() {
  const b = useTierBranding();

  // Stable primitives extracted to avoid referential instability in deps.
  const enabled = b.enabled;
  const tier = b.enabled ? b.tier : null;
  const label = b.enabled ? b.brand.label : null;

  useEffect(() => {
    if (!enabled || tier === "free") {
      // No-op for free tier and local mode.
      return;
    }

    document.title = `[${label}] ${CANONICAL_TITLE}`;

    return () => {
      // Restore canonical title on unmount or when tier changes.
      document.title = CANONICAL_TITLE;
    };
  }, [enabled, tier, label]);

  return null;
}
