"use client";

import type { ReactNode } from "react";
import { NotAvailableInDeployment } from "~/components/billing/not-available-in-deployment";
import { PlanRequired } from "~/components/billing/plan-required";
import { useSubscription } from "~/lib/subscription-context";

export interface EvalsGateState {
  /** True when every eval route may be called. */
  enabled: boolean;
  /** Still waiting on the entitlement row or the deployment capabilities. */
  loading: boolean;
  /** The screen to show instead of the page when not enabled; null while loading. */
  blocker: ReactNode | null;
}

/**
 * Plan prompt for free orgs, deployment notice when the runner is not
 * configured, otherwise the page. Order matters: a free org gets the plan
 * prompt even when the deployment could not run evals, because the plan is
 * the thing the customer can change.
 */
export function useEvalsGate(): EvalsGateState {
  const { isLoaded, isBillable, capabilities, capabilitiesLoaded } = useSubscription();

  if (!isLoaded) return { enabled: false, loading: true, blocker: null };
  if (!isBillable) {
    return {
      enabled: false,
      loading: false,
      blocker: (
        <PlanRequired
          feature="evals"
          description="Grade proposed knowledge entries against your eval suite before approving them, and track agent accuracy over time."
          compact
        />
      ),
    };
  }
  if (!capabilitiesLoaded) return { enabled: false, loading: true, blocker: null };
  if (capabilities?.evals !== true) {
    return {
      enabled: false,
      loading: false,
      blocker: <NotAvailableInDeployment capability="evals" feature="evals" compact />,
    };
  }
  return { enabled: true, loading: false, blocker: null };
}
