import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DashboardRenderBoundary } from "~/components/dashboard/dashboard-render-boundary";

function BrokenChart(): never {
  throw new Error("provider details stay in the browser");
}

describe("DashboardRenderBoundary", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    vi.spyOn(console, "error").mockImplementation(() => undefined);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.restoreAllMocks();
  });

  it("shows a safe tile state and emits only a bounded fingerprint", async () => {
    const onFailure = vi.fn();
    await act(async () => {
      root.render(
        <DashboardRenderBoundary resetKey="execution-1" onFailure={onFailure}>
          <BrokenChart />
        </DashboardRenderBoundary>,
      );
    });

    expect(container.textContent).toContain("Unable to display this chart");
    expect(container.textContent).not.toContain("provider details");
    expect(onFailure).toHaveBeenCalledOnce();
    expect(onFailure.mock.calls[0]?.[0]).toMatch(/^render-[a-f0-9]+$/);

    await act(async () => {
      root.render(
        <DashboardRenderBoundary resetKey="execution-2" onFailure={onFailure}>
          <span>Recovered chart</span>
        </DashboardRenderBoundary>,
      );
    });
    expect(container.textContent).toContain("Recovered chart");
  });
});
