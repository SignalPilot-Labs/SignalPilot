import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DashboardControlBar } from "~/components/dashboard/dashboard-control-bar";
import fiveComponents from "~/dashboard/lightdash-contract/fixtures/five-components.json";
import { fromLightdashFixture } from "~/dashboard/lightdash-contract";

describe("DashboardControlBar", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  it("renders nothing when the dashboard has no filter controls", async () => {
    const definition = fromLightdashFixture(fiveComponents);
    definition.filters.dimensions = [];
    await act(async () => {
      root.render(
        <DashboardControlBar
          dashboardId="dashboard-1"
          versionId="version-1"
          definition={definition}
          filters={[]}
          onChange={vi.fn()}
          onReset={vi.fn()}
        />,
      );
    });
    expect(container.childElementCount).toBe(0);
  });
});
