import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  LOCAL_PERMISSIONS,
  MEMBER_PERMISSIONS,
  UNLOADED_MEMBER_PERMISSIONS,
  permissionsFromPayload,
  type PermissionSet,
} from "~/lib/permissions";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const mocks = vi.hoisted(() => ({
  isCloudMode: true,
  permissions: null as PermissionSet | null,
}));

vi.mock("~/lib/auth-context", () => ({
  useAppAuth: () => ({ isCloudMode: mocks.isCloudMode, isLocalMode: !mocks.isCloudMode }),
}));

vi.mock("~/lib/subscription-context", () => ({
  useSubscription: () => ({ permissions: mocks.permissions }),
}));

import { usePermissions, type UsePermissions } from "~/lib/hooks/use-permissions";

function Probe({ onRender }: { onRender: (p: UsePermissions) => void }) {
  onRender(usePermissions());
  return null;
}

describe("usePermissions", () => {
  let container: HTMLDivElement;
  let root: Root;
  let last: UsePermissions | null;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    last = null;
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  async function render() {
    await act(async () => {
      root.render(<Probe onRender={(p) => (last = p)} />);
    });
    return last!;
  }

  it("is admin with every permission in local mode", async () => {
    mocks.isCloudMode = false;
    mocks.permissions = UNLOADED_MEMBER_PERMISSIONS;
    const p = await render();
    expect(p.role).toBe("admin");
    expect(p.isAdmin).toBe(true);
    expect(p.loaded).toBe(true);
    expect(p.can("billing.manage")).toBe(true);
    expect(p.can("keys.personal")).toBe(true);
  });

  it("reports an admin from the server payload", async () => {
    mocks.isCloudMode = true;
    mocks.permissions = permissionsFromPayload({
      role: "admin",
      is_admin: true,
      permissions: ["connections.write", "usage.org", "keys.personal"],
    });
    const p = await render();
    expect(p.isAdmin).toBe(true);
    expect(p.loaded).toBe(true);
    expect(p.can("connections.write")).toBe(true);
    // Only what the server listed: the hook does not widen an admin.
    expect(p.can("team.manage")).toBe(false);
  });

  it("reports a member with only member permissions", async () => {
    mocks.isCloudMode = true;
    mocks.permissions = permissionsFromPayload({
      role: "member",
      is_admin: false,
      permissions: [...MEMBER_PERMISSIONS],
    });
    const p = await render();
    expect(p.role).toBe("member");
    expect(p.isAdmin).toBe(false);
    expect(p.can("keys.personal")).toBe(true);
    expect(p.can("knowledge.propose")).toBe(true);
    expect(p.can("connections.write")).toBe(false);
    expect(p.can("billing.manage")).toBe(false);
  });

  it("treats a cloud user as an unloaded member before the server answers", async () => {
    mocks.isCloudMode = true;
    mocks.permissions = UNLOADED_MEMBER_PERMISSIONS;
    const p = await render();
    expect(p.loaded).toBe(false);
    expect(p.isAdmin).toBe(false);
    expect(p.can("settings.write")).toBe(false);
  });
});

describe("permissionsFromPayload", () => {
  it("falls back to the role default set when the list is missing", () => {
    const admin = permissionsFromPayload({ is_admin: true });
    expect(admin.role).toBe("admin");
    expect(admin.permissions.has("connections.write")).toBe(true);
    const member = permissionsFromPayload({ is_admin: false });
    expect(member.role).toBe("member");
    expect(member.permissions.has("connections.write")).toBe(false);
    expect(member.permissions.has("usage.self")).toBe(true);
  });

  it("prefers the explicit role over is_admin", () => {
    const set = permissionsFromPayload({ role: "member", is_admin: true });
    expect(set.role).toBe("member");
  });

  it("local set holds the full vocabulary", () => {
    expect(LOCAL_PERMISSIONS.permissions.has("branch.production_write")).toBe(true);
  });
});
