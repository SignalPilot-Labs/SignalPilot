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

import { IntegrationConnectButton } from "./integration-connect-button";

describe("IntegrationConnectButton", () => {
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

  it("renders no install button for a member (header slot)", async () => {
    await act(async () =>
      root.render(
        <IntegrationConnectButton label="connect notion" icon={<span />} onConnect={() => {}} connecting={false} />,
      ),
    );
    expect(container.querySelector("button")).toBeNull();
    expect(container.querySelector('[data-testid="integration-connect"]')).toBeNull();
  });

  it("renders the read-only note instead of the install button for a member (empty slot)", async () => {
    await act(async () =>
      root.render(
        <IntegrationConnectButton
          variant="empty"
          label="connect slack"
          icon={<span />}
          onConnect={() => {}}
          connecting={false}
        />,
      ),
    );
    expect(container.querySelector("button")).toBeNull();
    expect(container.querySelector('[data-testid="read-only-note"]')).not.toBeNull();
    expect(container.textContent).toContain("Managed by your org admins");
  });

  it("renders a working install button for an admin", async () => {
    mocks.granted = new Set(["integrations.write"]);
    const onConnect = vi.fn();
    await act(async () =>
      root.render(
        <IntegrationConnectButton label="connect notion" icon={<span />} onConnect={onConnect} connecting={false} />,
      ),
    );
    const button = container.querySelector<HTMLButtonElement>('[data-testid="integration-connect"]');
    expect(button).not.toBeNull();
    expect(button?.textContent).toContain("connect notion");
    await act(async () => button?.click());
    expect(onConnect).toHaveBeenCalledTimes(1);
  });
});
