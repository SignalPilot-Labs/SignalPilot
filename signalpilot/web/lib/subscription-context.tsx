"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  type ReactNode,
} from "react";
import { useAppAuth } from "@/lib/auth-context";
import { useBackendClient } from "@/lib/backend-client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface SubscriptionState {
  planTier: string;
  status: string;
  maxApiKeys: number;
  isLoaded: boolean;
  canCreateKey: (currentCount: number) => boolean;
  refetch: () => void;
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

const SubscriptionContext = createContext<SubscriptionState | null>(null);

// ---------------------------------------------------------------------------
// Local mode static values — local deployments always have full team-tier access
// ---------------------------------------------------------------------------

const LOCAL_MODE_SUBSCRIPTION: Omit<SubscriptionState, "canCreateKey" | "refetch"> = {
  planTier: "team",
  status: "active",
  maxApiKeys: 50,
  isLoaded: true,
};

// ---------------------------------------------------------------------------
// Inner component — called only when isCloudMode && clerkEnabled so hooks work
// ---------------------------------------------------------------------------

function CloudSubscriptionInner({ children }: { children: ReactNode }) {
  const { isAuthenticated } = useAppAuth();
  const client = useBackendClient();

  const [planTier, setPlanTier] = useState("free");
  const [status, setStatus] = useState("active");
  const [maxApiKeys, setMaxApiKeys] = useState(50);
  const [isLoaded, setIsLoaded] = useState(true);

  const fetchSubscription = useCallback(async () => {
    if (!isAuthenticated) {
      setIsLoaded(true);
      return;
    }
    try {
      const data = await client.getSubscription();
      setPlanTier(data.plan_tier);
      setStatus(data.status);
      setMaxApiKeys(data.max_api_keys);
    } catch {
      // Surface error by leaving defaults (free tier) and marking loaded
      // so the UI renders rather than spinning indefinitely
    } finally {
      setIsLoaded(true);
    }
  }, [isAuthenticated, client]);

  useEffect(() => {
    fetchSubscription();
  }, [fetchSubscription]);

  const value: SubscriptionState = {
    planTier,
    status,
    maxApiKeys,
    isLoaded,
    canCreateKey: (currentCount: number) => currentCount < maxApiKeys,
    refetch: fetchSubscription,
  };

  return (
    <SubscriptionContext.Provider value={value}>
      {children}
    </SubscriptionContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// SubscriptionProvider — wraps children, selects cloud vs local mode branch
// ---------------------------------------------------------------------------

export function SubscriptionProvider({ children }: { children: ReactNode }) {
  const { isCloudMode } = useAppAuth();

  if (isCloudMode) {
    return <CloudSubscriptionInner>{children}</CloudSubscriptionInner>;
  }

  // Local mode: static full-access subscription, no hooks needed
  const value: SubscriptionState = {
    ...LOCAL_MODE_SUBSCRIPTION,
    canCreateKey: (currentCount: number) =>
      currentCount < LOCAL_MODE_SUBSCRIPTION.maxApiKeys,
    refetch: () => {},
  };

  return (
    <SubscriptionContext.Provider value={value}>
      {children}
    </SubscriptionContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useSubscription(): SubscriptionState {
  const ctx = useContext(SubscriptionContext);
  if (ctx === null) {
    throw new Error("useSubscription must be called inside SubscriptionProvider");
  }
  return ctx;
}
