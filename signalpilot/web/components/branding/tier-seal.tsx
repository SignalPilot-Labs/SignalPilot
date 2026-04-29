"use client";

import { useOrganization } from "@clerk/nextjs";
import { type TierBrand } from "@/lib/tier-branding";
import { useTierBranding } from "@/lib/hooks/use-tier-branding";

/**
 * TierSeal — sidebar footer brand mark. Branches by tier so inner components
 * can call hooks unconditionally (rules-of-hooks).
 *
 * - enterprise → EnterpriseSealInner (calls useOrganization, renders org name)
 * - team       → TeamSealInner      (no useOrganization, no org line)
 * - else       → null
 */
export function TierSeal() {
  const b = useTierBranding();

  if (!b.enabled) return null;

  if (b.tier === "enterprise") {
    return <EnterpriseSealInner brand={b.brand} />;
  }

  if (b.tier === "team") {
    return <TeamSealInner brand={b.brand} />;
  }

  return null;
}

interface InnerProps {
  brand: TierBrand;
}

function EnterpriseSealInner({ brand }: InnerProps) {
  const { organization } = useOrganization();
  const orgName = organization?.name ?? null;

  if (!brand.accentHex) return null;

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

function TeamSealInner({ brand }: InnerProps) {
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
