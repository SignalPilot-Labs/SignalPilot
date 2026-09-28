import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const mocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("~/lib/api", () => ({ getTableauIntegration: mocks.get }));

import { TABLEAU_CHIP_TOOLTIP, TableauChip } from "~/components/chat/tableau-chip";

describe("TableauChip", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    mocks.get.mockReset();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async () => {
    await act(async () => {
      root.render(<TableauChip />);
    });
  };

  it("is hidden when the integration is not active", async () => {
    mocks.get.mockResolvedValue({ configured: true, enabled: false, active: false });
    await render();
    expect(container.querySelector("[data-testid=chat-tableau-chip]")).toBeNull();
  });

  it("is hidden when the request fails", async () => {
    mocks.get.mockRejectedValue(new Error("404: Not Found"));
    await render();
    expect(container.querySelector("[data-testid=chat-tableau-chip]")).toBeNull();
  });

  it("links to the integrations card when active", async () => {
    mocks.get.mockResolvedValue({ configured: true, enabled: true, active: true });
    await render();
    const chip = container.querySelector<HTMLAnchorElement>("[data-testid=chat-tableau-chip]");
    expect(chip).not.toBeNull();
    expect(chip?.getAttribute("href")).toBe("/integrations#tableau");
    expect(chip?.getAttribute("title")).toBe(TABLEAU_CHIP_TOOLTIP);
    expect(chip?.textContent).toContain("Tableau connected");
    expect(mocks.get).toHaveBeenCalledTimes(1);
  });
});
