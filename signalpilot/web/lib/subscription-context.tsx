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
  refetch: () => void;
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
}

function useBootstrapProbe(enabled: boolean): BootstrapProbe {
  const { data, error } = useSWR(
    enabled ? "standalone-chat-bootstrap" : null,
    getStandaloneChatBootstrap,
    { revalidateOnFocus: false, shouldRetryOnError: false },
  );
  return useMemo(() => {
    if (!enabled) return { capabilities: null, loaded: false, entitlement: null };
    if (data) {
      return {
        capabilities: data.capabilities ?? { evals: false, sandbox: false },
        loaded: true,
        entitlement: data.entitlement ? entitlementFromPayload(data.entitlement) : null,
      };
    }
    // A 402 means the org is not on a billable plan; the gateway still knows
    // nothing about the deployment for this caller, so capabilities stay null.
    if (error) return { capabilities: null, loaded: true, entitlement: null };
    return { capabilities: null, loaded: false, entitlement: null };
  }, [enabled, data, error]);
}

function buildState(
  row: RowState,
  probe: BootstrapProbe,
  isLoaded: boolean,
  loadError: string | null,
  refetch: () => void,
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

  const fetchSubscription = useCallback(async () => {
    if (!authLoaded) return;
    if (!isAuthenticated) {
      setIsLoaded(true);
      return;
    }
    try {
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
  }, [authLoaded, isAuthenticated, client]);

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
  { capabilities: null, loaded: false, entitlement: null },
  false,
  null,
  () => {},
);

export function useSubscription(): SubscriptionState {
  const ctx = useContext(SubscriptionContext);
  return ctx ?? FALLBACK_SUBSCRIPTION;
}
