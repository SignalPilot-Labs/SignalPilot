"use client";

import { useOrganization } from "@clerk/nextjs";
import { TIER_BRANDS } from "@/lib/tier-branding";
import { useTierBranding } from "@/lib/hooks/use-tier-branding";

const Crown = TIER_BRANDS.enterprise.icon;

interface TierSealProps {
  variant: "footer" | "header";
}

// Split into outer gate + inner mount so useOrganization() never runs outside
// cloud+enterprise (Clerk hook is unsafe in local mode).
export function TierSeal({ variant }: TierSealProps) {
  const b = useTierBranding();

  if (!b.enabled || b.tier !== "enterprise") return null;

  return <EnterpriseSealInner variant={variant} />;
}

function EnterpriseSealInner({ variant }: TierSealProps) {
  const { organization } = useOrganization();
  const orgName = organization?.name ?? null;

  if (variant === "footer") {
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

  return (
    <span className="inline-flex items-center gap-1.5 text-amber-300 tracking-[0.2em] uppercase text-[11px]">
      {Crown && (
        <Crown size={12} className="flex-shrink-0" aria-hidden="true" />
      )}
      ENTERPRISE
    </span>
  );
}
