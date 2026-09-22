import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Permission } from "~/lib/permissions";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const mocks = vi.hoisted(() => ({
  granted: new Set<string>(),
  orgName: "Acme Analytics" as string | null,
}));

vi.mock("~/lib/hooks/use-permissions", () => ({
  usePermissions: () => ({
    role: "member",
    isAdmin: false,
    loaded: true,
    can: (p: Permission) => mocks.granted.has(p),
  }),
}));

vi.mock("~/lib/auth-context", () => ({
  useAppAuth: () => ({ isCloudMode: true, activeOrgName: mocks.orgName }),
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

import { AdminOnlyPage } from "~/components/access/admin-only-page";
import { AdminOnlyControl, ADMIN_ONLY_TOOLTIP } from "~/components/access/admin-only-control";
import { ReadOnlyNote } from "~/components/access/read-only-note";

describe("access affordances", () => {
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

  it("AdminOnlyPage names the org and links back", async () => {
    await act(async () =>
      root.render(<AdminOnlyPage title="billing" what="plans and invoices" backHref="/settings/usage" backLabel="back to usage" />),
    );
    expect(container.querySelector('[data-testid="admin-only-page"]')).not.toBeNull();
    expect(container.textContent).toContain("Org admins manage this");
    expect(container.textContent).toContain("Acme Analytics");
    expect(container.textContent).toContain("Plans and invoices");
    const link = container.querySelector("a");
    expect(link?.getAttribute("href")).toBe("/settings/usage");
    expect(link?.textContent).toContain("back to usage");
  });

  it("AdminOnlyPage falls back when no org is active", async () => {
    mocks.orgName = null;
    await act(async () => root.render(<AdminOnlyPage title="team" />));
    expect(container.textContent).toContain("your organization");
    mocks.orgName = "Acme Analytics";
  });

  it("AdminOnlyControl renders the child as is for a holder of the permission", async () => {
    mocks.granted = new Set(["connections.write"]);
    await act(async () =>
      root.render(
        <AdminOnlyControl permission="connections.write">
          <button>save</button>
        </AdminOnlyControl>,
      ),
    );
    expect(container.querySelector('[data-testid="admin-only-control"]')).toBeNull();
    expect(container.querySelector("button")?.disabled).toBe(false);
  });

  it("AdminOnlyControl disables the child and carries the tooltip for others", async () => {
    mocks.granted = new Set();
    await act(async () =>
      root.render(
        <AdminOnlyControl permission="connections.write">
          <button>save</button>
        </AdminOnlyControl>,
      ),
    );
    const wrapper = container.querySelector<HTMLFieldSetElement>('[data-testid="admin-only-control"]');
    expect(wrapper).not.toBeNull();
    expect(wrapper?.disabled).toBe(true);
    // A disabled fieldset disables the native controls inside it.
    expect(container.querySelector("button")?.matches(":disabled")).toBe(true);
    await act(async () => {
      // React listens for mouseover (not mouseenter); focus is the keyboard path.
      wrapper!.parentElement!.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
      await new Promise((r) => setTimeout(r, 250));
    });
    expect(container.textContent).toContain(ADMIN_ONLY_TOOLTIP);
  });

  it("AdminOnlyControl honours an explicit allowed flag", async () => {
    mocks.granted = new Set();
    await act(async () =>
      root.render(
        <AdminOnlyControl permission="connections.write" allowed>
          <button>save</button>
        </AdminOnlyControl>,
      ),
    );
    expect(container.querySelector('[data-testid="admin-only-control"]')).toBeNull();
  });

  it("ReadOnlyNote carries the fixed lead and a detail", async () => {
    await act(async () => root.render(<ReadOnlyNote block>credentials stay redacted</ReadOnlyNote>));
    expect(container.textContent).toContain("Managed by your org admins");
    expect(container.textContent).toContain("credentials stay redacted");
  });
});
