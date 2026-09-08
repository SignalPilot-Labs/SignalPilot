import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DashboardVersion } from "~/lib/api/dashboards";
import { FIXTURE_NOW, FIXTURE_VERSION_IDS, fixtureVersions } from "~/lib/dashboards/fixture";
import { createFixtureDashboardsApi } from "~/lib/dashboards/fixture-api";
import { FIXTURE_DASHBOARD_ID } from "~/lib/dashboards/fixture";

import { DashboardVersionList } from "./dashboard-version-list";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

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

describe("DashboardVersionList", () => {
  it("marks the current version and offers Restore on the others", async () => {
    await act(async () => {
      root.render(
        <DashboardVersionList
          versions={fixtureVersions()}
          currentVersionId={FIXTURE_VERSION_IDS.v3}
          canEdit
          now={() => FIXTURE_NOW}
          onRestore={async () => {}}
          onDownloadDataset={async () => {}}
        />,
      );
    });
    const rows = container.querySelectorAll('[data-testid="dashboard-version-row"]');
    expect(rows).toHaveLength(3);
    expect(container.querySelectorAll('[data-testid="dashboard-version-current"]')).toHaveLength(1);
    expect(rows[0].getAttribute("data-current")).toBe("1");
    expect(rows[0].textContent).toContain("Restored");
    expect(rows[0].textContent).toContain("2 h ago");
    expect(container.querySelectorAll('[data-testid="dashboard-version-restore"]')).toHaveLength(2);
  });

  it("hides Restore for viewers who cannot edit", async () => {
    await act(async () => {
      root.render(
        <DashboardVersionList
          versions={fixtureVersions()}
          currentVersionId={FIXTURE_VERSION_IDS.v3}
          canEdit={false}
          onRestore={async () => {}}
          onDownloadDataset={async () => {}}
        />,
      );
    });
    expect(container.querySelectorAll('[data-testid="dashboard-version-restore"]')).toHaveLength(0);
  });

  it("Restore calls restoreDashboardVersion with the dashboard and version ids", async () => {
    const api = createFixtureDashboardsApi();
    const restore = vi.spyOn(api, "restoreDashboardVersion");
    await act(async () => {
      root.render(
        <DashboardVersionList
          versions={fixtureVersions()}
          currentVersionId={FIXTURE_VERSION_IDS.v3}
          canEdit
          onRestore={async (version) => {
            await api.restoreDashboardVersion(FIXTURE_DASHBOARD_ID, version.id);
          }}
          onDownloadDataset={async () => {}}
        />,
      );
    });
    const buttons = container.querySelectorAll<HTMLButtonElement>('[data-testid="dashboard-version-restore"]');
    // Rows are newest first: the first Restore belongs to v2.
    await act(async () => buttons[0].click());
    expect(restore).toHaveBeenCalledWith(FIXTURE_DASHBOARD_ID, FIXTURE_VERSION_IDS.v2);
    const { versions } = await api.getDashboard(FIXTURE_DASHBOARD_ID);
    expect(versions[0].version_no).toBe(4);
    expect(versions[0].produced_by).toBe("restore");
  });

  it("expands a version to its dataset files and downloads one", async () => {
    const onDownloadDataset = vi.fn<(version: DashboardVersion, name: string) => Promise<void>>(async () => {});
    await act(async () => {
      root.render(
        <DashboardVersionList
          versions={fixtureVersions()}
          currentVersionId={FIXTURE_VERSION_IDS.v3}
          canEdit
          onRestore={async () => {}}
          onDownloadDataset={onDownloadDataset}
        />,
      );
    });
    expect(container.querySelectorAll('[data-testid="dashboard-version-datasets"]')).toHaveLength(0);
    const toggles = container.querySelectorAll<HTMLButtonElement>('[data-testid="dashboard-version-toggle"]');
    await act(async () => toggles[1].click());
    const rows = container.querySelectorAll('[data-testid="dashboard-version-dataset"]');
    expect([...rows].map((row) => row.getAttribute("data-dataset"))).toEqual(["revenue_monthly", "revenue_by_region"]);
    expect(rows[0].textContent).toContain("revenue_monthly.csv");
    expect(rows[0].textContent).toContain("48 rows");
    await act(async () => {
      rows[1].querySelector<HTMLButtonElement>('[data-testid="dashboard-version-dataset-download"]')?.click();
    });
    expect(onDownloadDataset).toHaveBeenCalledTimes(1);
    expect(onDownloadDataset.mock.calls[0][0].id).toBe(FIXTURE_VERSION_IDS.v2);
    expect(onDownloadDataset.mock.calls[0][1]).toBe("revenue_by_region");
    // The fixture API serves the stored bytes for that version.
    const api = createFixtureDashboardsApi();
    const blob = await api.fetchDashboardDataset(FIXTURE_DASHBOARD_ID, FIXTURE_VERSION_IDS.v2, "revenue_by_region");
    expect(blob.type).toBe("application/json");
    expect(JSON.parse(await blob.text())).toHaveLength(4);
    await expect(api.fetchDashboardDataset(FIXTURE_DASHBOARD_ID, FIXTURE_VERSION_IDS.v2, "nope")).rejects.toThrow(/404/);
    // Toggling again collapses.
    await act(async () => toggles[1].click());
    expect(container.querySelectorAll('[data-testid="dashboard-version-datasets"]')).toHaveLength(0);
  });
});
