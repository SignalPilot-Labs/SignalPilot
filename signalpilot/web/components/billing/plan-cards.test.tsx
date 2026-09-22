import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { PlanInfo } from "~/lib/backend-client";
import { PlanCard } from "~/components/billing/plan-card";
import { EnterpriseCard } from "~/components/billing/enterprise-card";
import { PlanGrid } from "~/components/billing/plan-grid";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

import { ENTERPRISE, SCALE, TEAM } from "~/lib/billing-plan-review.test";

describe("plan cards", () => {
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

  it("shows the published fee per month, the yearly term, the 3-month option and the allowances from Stripe", async () => {
    await act(async () =>
      root.render(
        <PlanGrid plans={[TEAM, SCALE, ENTERPRISE]} currentTier="free" onSelect={() => {}} />,
      ),
    );
    const team = container.querySelector('[data-testid="plan-card-team"]')!;
    const scale = container.querySelector('[data-testid="plan-card-scale"]')!;
    expect(team.querySelector('[data-testid="plan-price"]')?.textContent).toBe("$100");
    expect(scale.querySelector('[data-testid="plan-price"]')?.textContent).toBe("$250");
    expect(scale.querySelector('[data-testid="plan-term"]')?.textContent).toBe("$3,000 billed yearly");
    expect(scale.textContent).toContain("or $900 every 3 months");
    expect(scale.textContent).toContain("15 seats");
    expect(scale.textContent).toContain("50 covered models");
    expect(scale.textContent).toContain("30 eval runs per month");
    expect(scale.textContent).toContain("10,000 credits per month");
    expect(container.textContent).not.toMatch(/billed monthly|month-to-month/i);
    expect(container.querySelectorAll("button").length).toBe(2);
    const enterprise = container.querySelector('[data-testid="plan-card-enterprise"]')!;
    expect(enterprise.querySelector('[data-testid="plan-price"]')?.textContent).toBe("Custom");
    expect(enterprise.textContent).toContain("one purchase order");
    expect(enterprise.textContent).toContain("100 seats");
    expect(enterprise.textContent).toContain("100,000 credits per month");
  });

  it("marks the current plan and labels higher and lower tiers", async () => {
    const onSelect = vi.fn();
    await act(async () =>
      root.render(<PlanGrid plans={[TEAM, SCALE, ENTERPRISE]} currentTier="scale" onSelect={onSelect} />),
    );
    const scale = container.querySelector('[data-testid="plan-card-scale"]')!;
    expect(scale.querySelector('[data-testid="plan-current"]')?.textContent).toContain("Current plan");
    expect(scale.querySelector('[data-testid="plan-select"]')).toBeNull();
    const teamButton = container.querySelector<HTMLButtonElement>('[data-testid="plan-card-team"] [data-testid="plan-select"]')!;
    expect(teamButton.textContent).toContain("Downgrade");
    await act(async () => teamButton.click());
    expect(onSelect).toHaveBeenCalledWith(TEAM);

    await act(async () =>
      root.render(<PlanGrid plans={[TEAM, SCALE, ENTERPRISE]} currentTier="team" onSelect={onSelect} />),
    );
    expect(
      container.querySelector('[data-testid="plan-card-scale"] [data-testid="plan-select"]')?.textContent,
    ).toContain("Upgrade");
  });

  it("keeps the pending-downgrade state on the target card", async () => {
    await act(async () =>
      root.render(
        <PlanCard
          plan={TEAM}
          currentTier="scale"
          pendingDowngradeTo="team"
          pendingDowngradeDate="2026-10-01"
          onSelect={() => {}}
        />,
      ),
    );
    expect(container.textContent).toContain("Active Oct 1");
    expect(container.querySelector('[data-testid="plan-select"]')).toBeNull();
  });

  it("enterprise card has no buy button, only Contact us", async () => {
    await act(async () => root.render(<EnterpriseCard plan={ENTERPRISE} isCurrent={false} />));
    expect(container.querySelector("button")).toBeNull();
    const contact = container.querySelector<HTMLAnchorElement>('[data-testid="enterprise-contact"]')!;
    expect(contact.textContent).toContain("Contact us");
    expect(contact.getAttribute("href")).toMatch(/^mailto:/);
    expect(container.textContent).toContain("one purchase order");
    expect(container.textContent).not.toMatch(/from \$|billed monthly/);
  });

  it("enterprise card without a published plan still offers contact and no numbers", async () => {
    await act(async () => root.render(<EnterpriseCard plan={null} isCurrent={false} />));
    expect(container.querySelector('[data-testid="plan-price"]')?.textContent).toBe("Custom");
    expect(container.textContent).toContain("allowances are set in the contract");
    expect(container.querySelector('[data-testid="enterprise-contact"]')).not.toBeNull();
  });

  it("an enterprise org sees only the enterprise card", async () => {
    await act(async () =>
      root.render(<PlanGrid plans={[TEAM, SCALE, ENTERPRISE]} currentTier="enterprise" onSelect={() => {}} />),
    );
    expect(container.querySelector('[data-testid="plan-card-team"]')).toBeNull();
    expect(container.querySelector('[data-testid="plan-card-scale"]')).toBeNull();
    const card = container.querySelector('[data-testid="plan-card-enterprise"]')!;
    expect(card.querySelector('[data-testid="plan-current"]')?.textContent).toContain("Current plan");
    expect(card.querySelector('[data-testid="enterprise-contact"]')?.textContent).toContain("Contact us for changes");
    expect(card.querySelector("button")).toBeNull();
  });
});
