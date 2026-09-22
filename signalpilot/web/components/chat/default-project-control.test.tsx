import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Permission } from "~/lib/permissions";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const mocks = vi.hoisted(() => ({ granted: new Set<string>() }));

vi.mock("~/lib/hooks/use-permissions", () => ({
  usePermissions: () => ({
    role: mocks.granted.has("chat.default_project") ? "admin" : "member",
    isAdmin: mocks.granted.has("chat.default_project"),
    loaded: true,
    can: (p: Permission) => mocks.granted.has(p),
  }),
}));

import { DefaultProjectControl } from "~/components/chat/default-project-control";

describe("DefaultProjectControl", () => {
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

  const button = () => container.querySelector<HTMLButtonElement>('[data-testid="chat-set-default-project"]');

  it("lets an admin set the picked project as the org default", async () => {
    mocks.granted = new Set(["chat.default_project"]);
    const onSetDefault = vi.fn();
    await act(async () =>
      root.render(
        <DefaultProjectControl selectedProjectId="p2" defaultProjectId="p1" onSetDefault={onSetDefault} />,
      ),
    );
    expect(container.querySelector('[data-testid="admin-only-control"]')).toBeNull();
    expect(button()!.matches(":disabled")).toBe(false);
    await act(async () => button()!.click());
    expect(onSetDefault).toHaveBeenCalledWith("p2");
  });

  it("shows a member the setter disabled with the admin-only rule", async () => {
    mocks.granted = new Set();
    const onSetDefault = vi.fn();
    await act(async () =>
      root.render(
        <DefaultProjectControl selectedProjectId="p2" defaultProjectId="p1" onSetDefault={onSetDefault} />,
      ),
    );
    expect(container.querySelector('[data-testid="admin-only-control"]')).not.toBeNull();
    expect(button()!.matches(":disabled")).toBe(true);
    await act(async () => button()!.click());
    expect(onSetDefault).not.toHaveBeenCalled();
  });

  it("labels the current org default instead of offering the setter", async () => {
    mocks.granted = new Set();
    await act(async () =>
      root.render(
        <DefaultProjectControl selectedProjectId="p1" defaultProjectId="p1" onSetDefault={vi.fn()} />,
      ),
    );
    expect(button()).toBeNull();
    expect(container.querySelector('[data-testid="chat-default-project-current"]')?.textContent).toContain("org default");
  });
});
