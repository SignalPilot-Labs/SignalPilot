import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { SubscriptionState } from "~/lib/subscription-context";
import { FREE_ENTITLEMENT, LOCAL_ENTITLEMENT, type Entitlement } from "~/lib/entitlement";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const mocks = vi.hoisted(() => ({ subscription: null as SubscriptionState | null }));

vi.mock("~/lib/subscription-context", () => ({
  useSubscription: () => mocks.subscription,
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

const TEAM: Entitlement = {
  ...FREE_ENTITLEMENT,
  tier: "team",
  isBillable: true,
  includedSeats: 10,
  includedModels: 30,
  includedEvalRuns: 30,
  includedCredits: 5_000,
};

function state(overrides: Partial<SubscriptionState>): SubscriptionState {
  const entitlement = overrides.entitlement ?? FREE_ENTITLEMENT;
  return {
    ...entitlement,
    entitlement,
    capabilities: null,
    capabilitiesLoaded: false,
    status: "active",
    currentPeriodEnd: null,
    graceUntil: null,
    contract: null,
    isLoaded: true,
    loadError: null,
    pendingDowngradeTo: null,
    pendingDowngradeDate: null,
    cancelAtPeriodEnd: false,
    cancelDate: null,
    refetch: () => {},
    ...overrides,
  };
}

import { PlanRequired } from "~/components/billing/plan-required";
import { NotAvailableInDeployment } from "~/components/billing/not-available-in-deployment";
import { useEvalsGate } from "~/components/billing/evals-gate";

function GateProbe() {
  const gate = useEvalsGate();
  return (
    <div data-testid="gate" data-enabled={gate.enabled} data-loading={gate.loading}>
      {gate.blocker}
    </div>
  );
}

describe("plan gates", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  it("PlanRequired names the feature, the current plan and links to the plan cards", async () => {
    mocks.subscription = state({ entitlement: FREE_ENTITLEMENT });
    await act(async () => root.render(<PlanRequired feature="evals" />));
    const card = container.querySelector('[data-testid="plan-required"]');
    expect(card?.textContent).toContain("Evals is part of every paid plan");
    expect(card?.textContent).toContain("Free plan");
    expect(card?.querySelector("a")?.getAttribute("href")).toBe("/settings/billing");
  });

  it("PlanRequired explains a paused past-due subscription", async () => {
    mocks.subscription = state({ entitlement: { ...TEAM, isBillable: false }, status: "past_due" });
    await act(async () => root.render(<PlanRequired feature="data chat" />));
    expect(container.textContent).toContain("past due");
    expect(container.textContent).toContain("Manage billing");
  });

  it("NotAvailableInDeployment tells the operator what is missing", async () => {
    await act(async () => root.render(<NotAvailableInDeployment capability="evals" feature="evals" />));
    const card = container.querySelector('[data-testid="not-available-in-deployment"]');
    expect(card?.textContent).toContain("SP_EVAL_RUNNER_IMAGE");
  });

  it("useEvalsGate: free org gets the plan prompt before anything else", async () => {
    mocks.subscription = state({ entitlement: FREE_ENTITLEMENT, capabilities: { evals: false, sandbox: false }, capabilitiesLoaded: true });
    await act(async () => root.render(<GateProbe />));
    const gate = container.querySelector('[data-testid="gate"]')!;
    expect(gate.getAttribute("data-enabled")).toBe("false");
    expect(gate.querySelector('[data-testid="plan-required"]')).not.toBeNull();
  });

  it("useEvalsGate: billable org waits for capabilities, then sees the deployment notice", async () => {
    mocks.subscription = state({ entitlement: TEAM });
    await act(async () => root.render(<GateProbe />));
    let gate = container.querySelector('[data-testid="gate"]')!;
    expect(gate.getAttribute("data-loading")).toBe("true");
    expect(gate.children.length).toBe(0);

    mocks.subscription = state({ entitlement: TEAM, capabilities: { evals: false, sandbox: true }, capabilitiesLoaded: true });
    await act(async () => root.render(<GateProbe key="2" />));
    gate = container.querySelector('[data-testid="gate"]')!;
    expect(gate.getAttribute("data-enabled")).toBe("false");
    expect(gate.querySelector('[data-testid="not-available-in-deployment"]')).not.toBeNull();
  });

  it("useEvalsGate: billable org on a capable deployment is enabled", async () => {
    mocks.subscription = state({ entitlement: TEAM, capabilities: { evals: true, sandbox: true }, capabilitiesLoaded: true });
    await act(async () => root.render(<GateProbe />));
    const gate = container.querySelector('[data-testid="gate"]')!;
    expect(gate.getAttribute("data-enabled")).toBe("true");
    expect(gate.children.length).toBe(0);
  });

  it("useEvalsGate: local mode is unlimited and billable", async () => {
    mocks.subscription = state({ entitlement: LOCAL_ENTITLEMENT, capabilities: { evals: true, sandbox: false }, capabilitiesLoaded: true });
    await act(async () => root.render(<GateProbe />));
    expect(container.querySelector('[data-testid="gate"]')?.getAttribute("data-enabled")).toBe("true");
  });
});
