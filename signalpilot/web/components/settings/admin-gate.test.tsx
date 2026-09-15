import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Permission } from "~/lib/permissions";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const mocks = vi.hoisted(() => ({
  granted: new Set<string>(),
}));

vi.mock("~/lib/hooks/use-permissions", () => ({
  usePermissions: () => ({
    role: mocks.granted.size ? "admin" : "member",
    isAdmin: mocks.granted.size > 0,
    loaded: true,
    can: (p: Permission) => mocks.granted.has(p),
  }),
}));

vi.mock("~/lib/auth-context", () => ({
  useAppAuth: () => ({ isCloudMode: true, activeOrgName: "Acme Analytics" }),
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

import { AdminGate } from "./admin-gate";

/** The billing page body, as `app/settings/billing/page.tsx` mounts it. */
function BillingPage() {
  return (
    <AdminGate permission="billing.manage" title="plans" subtitle="subscription" what="plans and invoices">
      <div data-testid="billing-content">plan grid</div>
    </AdminGate>
  );
}

describe("AdminGate (billing page)", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    mocks.granted = new Set();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  it("shows the admin-only notice to a member and never the billing content", async () => {
    await act(async () => root.render(<BillingPage />));
    expect(container.querySelector('[data-testid="admin-only-page"]')).not.toBeNull();
    expect(container.querySelector('[data-testid="billing-content"]')).toBeNull();
    expect(container.textContent).toContain("Org admins manage this");
    expect(container.textContent).toContain("Plans and invoices");
    expect(container.textContent).toContain("Acme Analytics");
  });

  it("renders the real content for an admin holding billing.manage", async () => {
    mocks.granted = new Set(["billing.manage"]);
    await act(async () => root.render(<BillingPage />));
    expect(container.querySelector('[data-testid="admin-only-page"]')).toBeNull();
    expect(container.querySelector('[data-testid="billing-content"]')?.textContent).toBe("plan grid");
  });

  it("keys on the named permission, not on any admin permission", async () => {
    mocks.granted = new Set(["byok.manage"]);
    await act(async () => root.render(<BillingPage />));
    expect(container.querySelector('[data-testid="admin-only-page"]')).not.toBeNull();
  });
});
