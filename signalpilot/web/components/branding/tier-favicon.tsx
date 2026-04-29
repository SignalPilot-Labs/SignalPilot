"use client";

import { useEffect } from "react";
import { useTierBranding } from "@/lib/hooks/use-tier-branding";

// Geometric SVG marks at 32×32. Solid fill-based, sharp corners, no stroke.
// Progressive corner-cut vocabulary on a centered 16×16 shape.
// Notches are 8×8 (half the shape side) so they survive downscale to 16×16 favicon:
//   pro        = solid square (no cuts)
//   team       = bottom-right corner cut (8×8 notch)
//   enterprise = both bottom corners cut (8×8 each, symmetric)
// Free tier: no favicon injection (handled by early return in useEffect).

const PRO_SVG =
  '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32"><rect x="8" y="8" width="16" height="16" fill="#9ca3af"/></svg>';

// bottom-right 8x8 cut: TL(8,8) TR(24,8) right-mid(24,16) notch-corner(16,24) BL(8,24)
const TEAM_SVG =
  '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32"><polygon points="8,8 24,8 24,16 16,24 8,24" fill="#60a5fa"/></svg>';

// both bottom corners cut (8x8 each): TL(8,8) TR(24,8) right-mid(24,16) (20,24) (12,24) left-mid(8,16)
const ENTERPRISE_SVG =
  '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32"><polygon points="8,8 24,8 24,16 20,24 12,24 8,16" fill="#00ff88"/></svg>';

const TIER_SVG: Record<string, string> = {
  enterprise: ENTERPRISE_SVG,
  team: TEAM_SVG,
  pro: PRO_SVG,
};

/**
 * Pure side-effect component. Returns null always.
 * Appends a <link data-tier-favicon="true"> for paid cloud tiers.
 * Browsers pick the last <link rel="icon"> match.
 * On unmount or tier change, removes only the tier-favicon element.
 * Original ico/svg/png links stay untouched.
 */
export function TierFavicon() {
  const b = useTierBranding();

  const enabled = b.enabled;
  const tier = b.enabled ? b.tier : null;

  useEffect(() => {
    if (!enabled || tier === "free" || tier === null) {
      return;
    }

    const svg = TIER_SVG[tier];
    if (!svg) return;

    const dataUrl = `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;

    const link = document.createElement("link");
    link.rel = "icon";
    link.setAttribute("data-tier-favicon", "true");
    link.href = dataUrl;
    document.head.appendChild(link);

    return () => {
      const existing = document.querySelector('link[data-tier-favicon="true"]');
      if (existing) {
        existing.remove();
      }
    };
  }, [enabled, tier]);

  return null;
}
