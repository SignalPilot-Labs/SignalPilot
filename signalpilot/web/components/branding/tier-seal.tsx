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
  const Icon = brand.icon;

  if (variant === "footer") {
    return (
      <div className="rounded border border-amber-400/30 bg-gradient-to-b from-amber-500/10 to-amber-500/5 overflow-hidden">
        <div className="h-px bg-amber-400/60" />
        <div className="px-3 py-2 flex flex-col gap-1">
          <div className="flex items-center gap-2">
            {Icon && (
              <Icon
                size={16}
                className="flex-shrink-0 text-amber-300/80"
                aria-hidden="true"
              />
            )}
            <span className="text-[10px] text-amber-300 tracking-[0.2em] uppercase">
              Enterprise Edition
            </span>
          </div>
          {orgName && (
            <span className="text-[10px] text-amber-300/60 tracking-wide pl-6">
              {orgName}
            </span>
          )}
        </div>
      </div>
    );
  }

  // Header variant — enterprise only, unchanged
  return (
    <span className="inline-flex items-center gap-1.5 text-amber-300 tracking-[0.2em] uppercase text-[11px]">
      {Icon && (
        <Icon size={12} className="flex-shrink-0" aria-hidden="true" />
      )}
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
  const Icon = brand.icon;

  return (
    <div className="rounded border border-violet-400/30 bg-gradient-to-b from-violet-500/10 to-violet-500/5 overflow-hidden">
      <div className="h-px bg-violet-400/60" />
      <div className="px-3 py-2 flex items-center gap-2">
        {Icon && (
          <Icon
            size={16}
            className="flex-shrink-0 text-violet-300/80"
            aria-hidden="true"
          />
        )}
        <span className="text-[10px] text-violet-300 tracking-[0.2em] uppercase">
          Team Edition
        </span>
      </div>
    </div>
  );
}
