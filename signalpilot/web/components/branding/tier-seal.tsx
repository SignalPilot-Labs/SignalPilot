"use client";

import { useOrganization } from "@clerk/nextjs";
import { type TierBrand } from "@/lib/tier-branding";
import { useTierBranding } from "@/lib/hooks/use-tier-branding";

interface TierSealProps {
  variant: "footer" | "header";
}

/**
 * TierSeal outer gate — branches by tier so inner components can call hooks
 * unconditionally (rules-of-hooks: no conditional hook calls).
 *
 * - enterprise → EnterpriseSealInner (calls useOrganization, renders org name)
 * - team       → TeamSealInner      (no useOrganization, no org line)
 * - else       → null
 *
 * Header variant gate stays enterprise-only (unchanged from prior spec).
 */
export function TierSeal({ variant }: TierSealProps) {
  const b = useTierBranding();

  if (!b.enabled) return null;

  if (b.tier === "enterprise") {
    return <EnterpriseSealInner variant={variant} brand={b.brand} />;
  }

  if (b.tier === "team" && variant === "footer") {
    return <TeamSealInner brand={b.brand} />;
  }

  return null;
}

// ---------------------------------------------------------------------------
// EnterpriseSealInner — safe to call useOrganization() here
// ---------------------------------------------------------------------------

interface EnterpriseSealInnerProps extends TierSealProps {
  brand: TierBrand;
}

function EnterpriseSealInner({ variant, brand }: EnterpriseSealInnerProps) {
  const { organization } = useOrganization();
  const orgName = organization?.name ?? null;

  if (!brand.accentHex) return null;

  if (variant === "footer") {
    return (
      <div className="flex flex-col gap-0.5">
        <div className="flex items-center gap-1.5">
          <span
            className="inline-block w-[5px] h-[5px] flex-shrink-0"
            style={{ backgroundColor: brand.accentHex }}
            aria-hidden="true"
          />
          <span className={`text-[10px] leading-none tracking-[0.2em] uppercase ${brand.accentText}`}>
            Enterprise
          </span>
        </div>
        {orgName && (
          <span className="text-[10px] text-[var(--color-text-dim)] tracking-wide pl-[11px]">
            {orgName}
          </span>
        )}
      </div>
    );
  }

  // Header variant — enterprise only
  return (
    <span className={`inline-flex items-center gap-1.5 leading-none tracking-[0.2em] uppercase text-[11px] ${brand.accentText}`}>
      <span
        className="inline-block w-[5px] h-[5px] flex-shrink-0"
        style={{ backgroundColor: brand.accentHex }}
        aria-hidden="true"
      />
      ENTERPRISE
    </span>
  );
}

// ---------------------------------------------------------------------------
// TeamSealInner — no useOrganization(); footer only
// ---------------------------------------------------------------------------

interface TeamSealInnerProps {
  brand: TierBrand;
}

function TeamSealInner({ brand }: TeamSealInnerProps) {
  if (!brand.accentHex) return null;

  return (
    <div className="flex items-center gap-1.5">
      <span
        className="inline-block w-[5px] h-[5px] flex-shrink-0"
        style={{ backgroundColor: brand.accentHex }}
        aria-hidden="true"
      />
      <span className={`text-[10px] leading-none tracking-[0.2em] uppercase ${brand.accentText}`}>
        Team
      </span>
    </div>
  );
}
