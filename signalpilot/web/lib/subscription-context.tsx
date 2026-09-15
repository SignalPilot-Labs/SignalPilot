"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import useSWR from "swr";
import { useAppAuth } from "~/lib/auth-context";
import { useBackendClient } from "~/lib/backend-client";
import { getStandaloneChatBootstrap } from "~/lib/api/standalone-chat";
import { gatingError } from "~/lib/api/client";
import {
  FREE_ENTITLEMENT,
  LOCAL_ENTITLEMENT,
  entitlementFromPayload,
  entitlementFromSubscription,
  type DeploymentCapabilities,
  type Entitlement,
} from "~/lib/entitlement";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * One source for every plan gate in the UI. `entitlement` is the row the org
 * is billed on; `capabilities` says what this deployment can run at all.
 */
export interface SubscriptionState extends Entitlement {
  entitlement: Entitlement;
  /** null until the gateway bootstrap has answered (or failed). */
  capabilities: DeploymentCapabilities | null;
  capabilitiesLoaded: boolean;
  status: string;
  currentPeriodEnd: string | null;
  graceUntil: string | null;
  contract: Record<string, unknown> | null;
  isLoaded: boolean;
  /** Set when the backend subscription row could not be read. */
  loadError: string | null;
  pendingDowngradeTo: string | null;
  pendingDowngradeDate: string | null;
  cancelAtPeriodEnd: boolean;
  cancelDate: string | null;
  /** Re-read the row; `refresh` also makes the gateway bypass its entitlement cache. */
  refetch: (options?: RefetchOptions) => void;
}

export interface RefetchOptions {
  refresh?: boolean;
}

interface RowState {
  entitlement: Entitlement;
  status: string;
  currentPeriodEnd: string | null;
  graceUntil: string | null;
  contract: Record<string, unknown> | null;
  pendingDowngradeTo: string | null;
  pendingDowngradeDate: string | null;
  cancelAtPeriodEnd: boolean;
  cancelDate: string | null;
}

const FREE_ROW: RowState = {
  entitlement: FREE_ENTITLEMENT,
  status: "active",
  currentPeriodEnd: null,
  graceUntil: null,
  contract: null,
  pendingDowngradeTo: null,
  pendingDowngradeDate: null,
  cancelAtPeriodEnd: false,
  cancelDate: null,
};

const LOCAL_ROW: RowState = { ...FREE_ROW, entitlement: LOCAL_ENTITLEMENT };

const SubscriptionContext = createContext<SubscriptionState | null>(null);

// ---------------------------------------------------------------------------
// Deployment capabilities — from the gateway bootstrap, both modes
// ---------------------------------------------------------------------------

interface BootstrapProbe {
  capabilities: DeploymentCapabilities | null;
  loaded: boolean;
  /** Entitlement as the gateway reports it; used when the backend row is unavailable. */
  entitlement: Entitlement | null;
  /** Re-read the bootstrap with the gateway's entitlement cache bypassed. */
  refresh: () => Promise<void>;
}

const FREE_PAYLOAD = {
  tier: "free",
  is_billable: false,
  included_seats: 0,
  included_models: 0,
  included_eval_runs: 0,
  included_credits: 0,
  managed: false,
} as const;

function useBootstrapProbe(enabled: boolean): BootstrapProbe {
  const { data, error, mutate } = useSWR(
    enabled ? "standalone-chat-bootstrap" : null,
    () => getStandaloneChatBootstrap(),
    { revalidateOnFocus: false, shouldRetryOnError: false },
  );
  const refresh = useCallback(async () => {
    await mutate(getStandaloneChatBootstrap({ refresh: true }), { revalidate: false });
  }, [mutate]);
  return useMemo(() => {
    if (!enabled) return { capabilities: null, loaded: false, entitlement: null, refresh };
    if (data) {
      // The gateway answers 200 for every org: a free org gets `enabled: false`
      // with its entitlement and the deployment capabilities.
      return {
        capabilities: data.capabilities ?? { evals: false, sandbox: false },
        loaded: true,
        entitlement: data.entitlement?.tier ? entitlementFromPayload(data.entitlement) : null,
        refresh,
      };
    }
    if (error) {
      // A gated route answers 402 plan_required with the tier; that is still
      // an entitlement. A 503 not_available_in_deployment says nothing about
      // the plan, and neither says what the deployment can run, so
      // capabilities stay null.
      const gate = gatingError(error);
      const entitlement =
        gate?.error === "plan_required"
          ? entitlementFromPayload({ ...FREE_PAYLOAD, tier: gate.tier })
          : null;
      return { capabilities: null, loaded: true, entitlement, refresh };
    }
    return { capabilities: null, loaded: false, entitlement: null, refresh };
  }, [enabled, data, error, refresh]);
}

function buildState(
  row: RowState,
  probe: BootstrapProbe,
  isLoaded: boolean,
  loadError: string | null,
  refetch: (options?: RefetchOptions) => void,
): SubscriptionState {
  return {
    ...row.entitlement,
    entitlement: row.entitlement,
    capabilities: probe.capabilities,
    capabilitiesLoaded: probe.loaded,
    status: row.status,
    currentPeriodEnd: row.currentPeriodEnd,
    graceUntil: row.graceUntil,
    contract: row.contract,
    isLoaded,
    loadError,
    pendingDowngradeTo: row.pendingDowngradeTo,
    pendingDowngradeDate: row.pendingDowngradeDate,
    cancelAtPeriodEnd: row.cancelAtPeriodEnd,
    cancelDate: row.cancelDate,
    refetch,
  };
}

// ---------------------------------------------------------------------------
// Cloud — the backend subscription row is the entitlement row
// ---------------------------------------------------------------------------

function CloudSubscriptionInner({ children }: { children: ReactNode }) {
  const { isAuthenticated, isLoaded: authLoaded } = useAppAuth();
  const client = useBackendClient();
  const probe = useBootstrapProbe(authLoaded && isAuthenticated);

  const [row, setRow] = useState<RowState>(FREE_ROW);
  // Starts false: consumers must wait for the real row before rendering,
  // otherwise the free default flashes a plan prompt for a frame on refresh.
  const [isLoaded, setIsLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const fetchSubscription = useCallback(async (options?: RefetchOptions) => {
    if (!authLoaded) return;
    if (!isAuthenticated) {
      setIsLoaded(true);
      return;
    }
    try {
      // After Stripe Checkout the gateway's cached entitlement may still say
      // free; a refreshed bootstrap makes it re-read the row now.
      if (options?.refresh) probe.refresh().catch(() => {});
      const data = await client.getSubscription();
      setRow({
        entitlement: entitlementFromSubscription(data),
        status: data.status,
        currentPeriodEnd: data.current_period_end,
        graceUntil: data.grace_until ?? null,
        contract: data.contract ?? null,
        pendingDowngradeTo: data.pending_downgrade_to,
        pendingDowngradeDate: data.pending_downgrade_date,
        cancelAtPeriodEnd: data.cancel_at_period_end ?? false,
        cancelDate: data.cancel_date ?? null,
      });
      setLoadError(null);
    } catch (e) {
      // Leave the free defaults and mark loaded so the UI renders instead of
      // spinning; the gateway's own view fills in below when it answered.
      setLoadError(e instanceof Error ? e.message : String(e));
    } finally {
      setIsLoaded(true);
    }
  }, [authLoaded, isAuthenticated, client, probe]);

  useEffect(() => {
    fetchSubscription();
  }, [fetchSubscription]);

  const value = useMemo(() => {
    const effectiveRow =
      loadError && probe.entitlement ? { ...row, entitlement: probe.entitlement } : row;
    return buildState(effectiveRow, probe, isLoaded, loadError, fetchSubscription);
  }, [row, probe, isLoaded, loadError, fetchSubscription]);

  return (
    <SubscriptionContext.Provider value={value}>
      {children}
    </SubscriptionContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// Local — unlimited and billable; capabilities still come from the gateway
// ---------------------------------------------------------------------------

function LocalSubscriptionInner({ children }: { children: ReactNode }) {
  const { isAuthenticated, isLoaded: authLoaded } = useAppAuth();
  const probe = useBootstrapProbe(authLoaded && isAuthenticated);
  const value = useMemo(
    () => buildState(LOCAL_ROW, probe, true, null, () => {}),
    [probe],
  );
  return (
    <SubscriptionContext.Provider value={value}>
      {children}
    </SubscriptionContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

export function SubscriptionProvider({ children }: { children: ReactNode }) {
  const { isCloudMode } = useAppAuth();
  if (isCloudMode) {
    return <CloudSubscriptionInner>{children}</CloudSubscriptionInner>;
  }
  return <LocalSubscriptionInner>{children}</LocalSubscriptionInner>;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

const FALLBACK_SUBSCRIPTION: SubscriptionState = buildState(
  FREE_ROW,
  { capabilities: null, loaded: false, entitlement: null, refresh: async () => {} },
  false,
  null,
  () => {},
);

export function useSubscription(): SubscriptionState {
  const ctx = useContext(SubscriptionContext);
  return ctx ?? FALLBACK_SUBSCRIPTION;
}
