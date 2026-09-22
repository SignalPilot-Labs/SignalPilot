import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { scopesForCaller } from "~/lib/api-key-scopes";
import { CreateKeyForm } from "~/app/settings/api-keys/_components/create-key-form";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

describe("CreateKeyForm scope limiting", () => {
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

  function offered(): string[] {
    return Array.from(container.querySelectorAll('[data-testid="scope-options"] label')).map(
      (l) => l.querySelector("span")?.textContent ?? "",
    );
  }

  it("a member sees only read, query and execute plus the personal note", async () => {
    await act(async () =>
      root.render(
        <CreateKeyForm
          createFn={vi.fn()}
          onCreated={() => {}}
          onCancel={() => {}}
          scopeOptions={scopesForCaller(false)}
          personal
        />,
      ),
    );
    expect(offered().sort()).toEqual(["execute", "query", "read"]);
    expect(container.textContent).toContain("Managed by your org admins");
  });

  it("an admin sees every scope", async () => {
    await act(async () =>
      root.render(
        <CreateKeyForm
          createFn={vi.fn()}
          onCreated={() => {}}
          onCancel={() => {}}
          scopeOptions={scopesForCaller(true)}
        />,
      ),
    );
    expect(offered()).toContain("admin");
    expect(offered()).toContain("write");
    expect(container.textContent).not.toContain("Managed by your org admins");
  });
});
