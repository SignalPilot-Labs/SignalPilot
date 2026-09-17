import { useAppAuth } from "~/lib/auth-context";
import { useSubscription } from "~/lib/subscription-context";
import { TIER_BRANDS, isBrandTier, type BrandTier, type TierBrand } from "~/lib/tier-branding";

type TierBrandingState =
  | { enabled: false }
  | { enabled: true; tier: BrandTier; brand: TierBrand };

/**
 * Brand state for the org's plan. Enabled only in cloud mode once the
 * entitlement row has loaded and the org is on a billable, branded tier.
 */
export function useTierBranding(): TierBrandingState {
  const { isCloudMode } = useAppAuth();
  const { tier, isBillable, isLoaded } = useSubscription();

  if (!isCloudMode || !isLoaded || !isBillable || !isBrandTier(tier)) {
    return { enabled: false };
  }

  return { enabled: true, tier, brand: TIER_BRANDS[tier] };
}
