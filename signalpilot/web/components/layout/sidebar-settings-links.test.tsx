import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ADMIN_PERMISSIONS, MEMBER_PERMISSIONS, type Permission } from "~/lib/permissions";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const mocks = vi.hoisted(() => ({
  granted: new Set<string>(),
  isAdmin: false,
}));

vi.mock("~/lib/hooks/use-permissions", () => ({
  usePermissions: () => ({
    role: mocks.isAdmin ? "admin" : "member",
    isAdmin: mocks.isAdmin,
    loaded: true,
    can: (p: Permission) => mocks.granted.has(p),
  }),
}));

vi.mock("~/lib/auth-context", () => ({
  useAppAuth: () => ({ isCloudMode: true, isLocalMode: false }),
}));

vi.mock("~/lib/subscription-context", () => ({
  useSubscription: () => ({ isLoaded: true, isBillable: true }),
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

import {
  BillingNavLink,
  ByokNavLink,
  McpConnectNavLink,
  TeamNavLink,
  UsageNavLink,
} from "~/components/layout/sidebar-settings-links";

function AllLinks() {
  return (
    <>
      <UsageNavLink pathname="/dashboard" />
      <BillingNavLink pathname="/dashboard" />
      <McpConnectNavLink pathname="/dashboard" />
      <ByokNavLink pathname="/dashboard" />
      <TeamNavLink pathname="/dashboard" />
    </>
  );
}

describe("sidebar settings links", () => {
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

  function hrefs(): string[] {
    return Array.from(container.querySelectorAll("a")).map((a) => a.getAttribute("href") ?? "");
  }

  it("hides billing, mcp-connect, byok and team from a member; usage becomes my usage", async () => {
    mocks.isAdmin = false;
    mocks.granted = new Set(MEMBER_PERMISSIONS);
    await act(async () => root.render(<AllLinks />));
    expect(hrefs()).toEqual(["/settings/usage"]);
    expect(container.textContent).toContain("my usage");
  });

  it("shows every link to an admin", async () => {
    mocks.isAdmin = true;
    mocks.granted = new Set(ADMIN_PERMISSIONS);
    await act(async () => root.render(<AllLinks />));
    expect(hrefs()).toEqual([
      "/settings/usage",
      "/settings/billing",
      "/settings/mcp-connect",
      "/settings/byok",
      "/settings/team",
    ]);
    expect(container.textContent).not.toContain("my usage");
  });
});
