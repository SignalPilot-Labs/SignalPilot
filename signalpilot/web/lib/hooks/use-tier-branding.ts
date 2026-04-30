import { useAppAuth } from "@/lib/auth-context";
import { useSubscription } from "@/lib/subscription-context";
import { TIER_BRANDS, type BrandTier, type TierBrand } from "@/lib/tier-branding";

type TierBrandingState =
  | { enabled: false }
  | { enabled: true; tier: BrandTier; brand: TierBrand };

export function useTierBranding(): TierBrandingState {
  const { isCloudMode } = useAppAuth();
  const { planTier, isLoaded } = useSubscription();

  if (!isCloudMode || !isLoaded || !(planTier in TIER_BRANDS)) {
    return { enabled: false };
  }

  const tier = planTier as BrandTier;
  return { enabled: true, tier, brand: TIER_BRANDS[tier] };
}
