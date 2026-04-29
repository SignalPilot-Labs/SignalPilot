"use client";

import type { LucideIcon } from "lucide-react";
import { useOrganization } from "@clerk/nextjs";
import { TIER_BRANDS } from "@/lib/tier-branding";
import { useTierBranding } from "@/lib/hooks/use-tier-branding";

interface TierSealProps {
  variant: "footer" | "header";
}

/**
 * Enterprise-only watermark seal. Returns null for all non-enterprise tiers.
 *
 * The component is split into two pieces for hooks-rules safety:
 * - TierSeal: outer gate that calls only useTierBranding(). Exits early for
 *   local mode or non-enterprise tiers, so useOrganization() never runs in
 *   those cases.
 * - EnterpriseSealInner: mounts only when TierSeal decides to render the seal.
 *   Calls useOrganization() unconditionally (safe — only mounted in cloud mode
 *   after Clerk is initialized).
 */
export function TierSeal({ variant }: TierSealProps) {
  const b = useTierBranding();

  // Gate: local mode or non-enterprise → nothing rendered, no Clerk hook called.
  if (!b.enabled || b.tier !== "enterprise") return null;

  return <EnterpriseSealInner variant={variant} />;
}

// ── Inner component — only ever mounted in cloud enterprise mode ──

interface EnterpriseSealInnerProps {
  variant: "footer" | "header";
}

function EnterpriseSealInner({ variant }: EnterpriseSealInnerProps) {
  // This component is ONLY mounted inside ClerkProvider (cloud + enterprise).
  const orgName = useEnterpriseOrgName();

  if (variant === "footer") {
    return <FooterSeal orgName={orgName} />;
  }

  return <HeaderSeal />;
}

// ── Clerk org name hook — unconditional call is safe here ──

function useEnterpriseOrgName(): string | null {
  const { organization } = useOrganization();
  return organization?.name ?? null;
}

// ── Shared helper: get Crown icon from config without re-importing lucide ──

function getCrownIcon(): LucideIcon | null {
  return TIER_BRANDS.enterprise.icon;
}

// ── Footer variant ──

function FooterSeal({ orgName }: { orgName: string | null }) {
  const Crown = getCrownIcon();

  return (
    <div className="flex items-center gap-2 py-2">
      {Crown && (
        <Crown
          size={14}
          className="flex-shrink-0 text-amber-300/30"
          aria-hidden="true"
        />
      )}
      <span className="text-[10px] text-[var(--color-text-dim)]/60 tracking-[0.2em] uppercase">
        enterprise edition{orgName ? ` · ${orgName}` : ""}
      </span>
    </div>
  );
}

// ── Header variant ──

function HeaderSeal() {
  const Crown = getCrownIcon();

  return (
    <span className="inline-flex items-center gap-1.5 text-amber-300 tracking-[0.2em] uppercase text-[11px]">
      {Crown && (
        <Crown size={12} className="flex-shrink-0" aria-hidden="true" />
      )}
      ENTERPRISE
    </span>
  );
}
