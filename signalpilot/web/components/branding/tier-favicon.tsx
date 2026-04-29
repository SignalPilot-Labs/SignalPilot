"use client";

import { useEffect } from "react";
import { useTierBranding } from "@/lib/hooks/use-tier-branding";

// Inline SVG string constants per tier — no react-dom/server, no extra HTTP fetch.
// Paths match Lucide Crown / Gem / Sparkles at 32×32 viewport.

const ENTERPRISE_SVG =
  '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#fbbf24" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11.562 3.266a.5.5 0 0 1 .876 0L15.39 8.87a1 1 0 0 0 1.516.294L21.183 6.5a.5.5 0 0 1 .798.519l-2.834 10.246a1 1 0 0 1-.956.735H5.81a1 1 0 0 1-.957-.735L2.02 7.019a.5.5 0 0 1 .797-.519l4.278 2.664a1 1 0 0 0 1.516-.294z"/><path d="M5 21h14"/></svg>';

const TEAM_SVG =
  '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#a78bfa" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 3l6 3 6-3v10l-6 3-6-3z"/><path d="M6 3v10"/><path d="M18 3v10"/><path d="M12 6v10"/></svg>';

const PRO_SVG =
  '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#818cf8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275z"/><path d="M5 3v4"/><path d="M19 17v4"/><path d="M3 5h4"/><path d="M17 19h4"/></svg>';

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
