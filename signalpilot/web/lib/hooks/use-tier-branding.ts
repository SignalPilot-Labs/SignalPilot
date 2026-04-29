import { useAppAuth } from "@/lib/auth-context";
import { useSubscription } from "@/lib/subscription-context";
import { getTierBrand, type BrandTier, type TierBrand } from "@/lib/tier-branding";

const KNOWN_TIERS = new Set<string>(["free", "pro", "team", "enterprise"]);

export type TierBrandingState =
  | { enabled: false }
  | { enabled: true; tier: BrandTier; brand: TierBrand };

export function useTierBranding(): TierBrandingState {
  const { isCloudMode } = useAppAuth();
  const { planTier, isLoaded } = useSubscription();

  if (!isCloudMode) {
    return { enabled: false };
  }

  if (!isLoaded) {
    return { enabled: false };
  }

  if (!KNOWN_TIERS.has(planTier)) {
    return { enabled: false };
  }

  const tier = planTier as BrandTier;
  const brand = getTierBrand(tier);

  return { enabled: true, tier, brand };
}
