import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiRequestError } from "~/lib/api/client";
import type { DashboardDetail } from "~/lib/api/dashboards";
import { FIXTURE_DASHBOARD_ID, FIXTURE_DASHBOARD_SLUG, fixtureDetail } from "~/lib/dashboards/fixture";
import { createFixtureDashboardsApi } from "~/lib/dashboards/fixture-api";

import { DashboardsApiProvider } from "./dashboards-api-context";
import {
  POLL_STOPPED_MESSAGE,
  REFRESH_POLL_MAX_FAILURES,
  REFRESH_POLL_MS,
  pollShouldStop,
  useDashboardDetail,
} from "./use-dashboard-detail";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

type Api = ReturnType<typeof createFixtureDashboardsApi>;
type HookValue = ReturnType<typeof useDashboardDetail>;

let container: HTMLDivElement;
let root: Root;
let latest: HookValue | null;

function Probe({ idOrSlug }: { idOrSlug: string }) {
  latest = useDashboardDetail(idOrSlug);
  return <span data-phase={latest.state.phase} />;
}

async function mount(api: Api, idOrSlug = FIXTURE_DASHBOARD_SLUG) {
  await act(async () => {
    root.render(
      <DashboardsApiProvider api={api}>
        <Probe idOrSlug={idOrSlug} />
      </DashboardsApiProvider>,
    );
  });
}

/** Resolve pending microtasks without advancing timers. */
const flush = () => act(async () => {});

beforeEach(() => {
  vi.useFakeTimers();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  latest = null;
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.useRealTimers();
});

const readyDetail = (): DashboardDetail => {
  if (!latest || latest.state.phase !== "ready") throw new Error(`phase ${latest?.state.phase}`);
  return latest.state.detail;
};

describe("useDashboardDetail", () => {
  it("loads the detail and the current bundle", async () => {
    // No running refresh: polling must not start.
    const api = createFixtureDashboardsApi({ agentRefreshCompletesMs: 0 });
    api.state.refreshes.set(FIXTURE_DASHBOARD_ID, []);
    await mount(api);
    await flush();
    expect(latest?.state.phase).toBe("ready");
    expect(readyDetail().dashboard.slug).toBe(FIXTURE_DASHBOARD_SLUG);
    expect(latest?.state.phase === "ready" && latest.state.bundle?.version.version_no).toBe(3);
    expect(latest?.refreshing).toBe(false);
  });

  it("drops a stale load that settles after a newer one", async () => {
    const api = createFixtureDashboardsApi({ agentRefreshCompletesMs: 0 });
    api.state.refreshes.set(FIXTURE_DASHBOARD_ID, []);
    let release: (() => void) | null = null;
    const original = api.getDashboard.bind(api);
    let calls = 0;
    api.getDashboard = async (idOrSlug) => {
      calls += 1;
      if (calls === 2) {
        // The second call hangs until released, then answers with a stale name.
        await new Promise<void>((resolve) => {
          release = resolve;
        });
        const detail = await original(idOrSlug);
        return { ...detail, dashboard: { ...detail.dashboard, name: "STALE" } };
      }
      return original(idOrSlug);
    };
    await mount(api);
    await flush();
    expect(readyDetail().dashboard.name).toBe("Revenue overview 2024");

    // Second load hangs; third load lands with the fresh name.
    const slow = latest!.reload();
    await flush();
    api.state.dashboards[0].name = "Fresh name";
    const fast = latest!.reload();
    await flush();
    expect(readyDetail().dashboard.name).toBe("Fresh name");
    expect(await fast).not.toBeNull();

    release!();
    await flush();
    expect(await slow).toBeNull();
    expect(readyDetail().dashboard.name).toBe("Fresh name");
  });

  it("polls while a refresh runs and swaps to the new version when it lands", async () => {
    // The manual refresh succeeds between the first and second poll.
    const api = createFixtureDashboardsApi({ agentRefreshCompletesMs: 0, refreshDurationMs: 7_000 });
    api.state.refreshes.set(FIXTURE_DASHBOARD_ID, []);
    const list = vi.spyOn(api, "listDashboardRefreshes");
    await mount(api);
    await flush();
    const { refresh } = await api.refreshDashboardNow(FIXTURE_DASHBOARD_ID);
    await act(async () => latest!.prependRefresh(refresh));
    expect(latest?.refreshing).toBe(true);

    await act(async () => {
      vi.advanceTimersByTime(REFRESH_POLL_MS);
    });
    await flush();
    expect(list).toHaveBeenCalledTimes(1);
    expect(latest?.refreshing).toBe(true);

    // The refresh completes at 7 s; the 10 s poll sees it and reloads.
    await act(async () => {
      vi.advanceTimersByTime(REFRESH_POLL_MS);
    });
    await flush();
    await flush();
    expect(latest?.refreshing).toBe(false);
    expect(readyDetail().dashboard.current_version_no).toBe(4);
    expect(latest?.state.phase === "ready" && latest.state.bundle?.version.version_no).toBe(4);
  });

  it("stops polling after three consecutive failures and surfaces an error", async () => {
    const api = createFixtureDashboardsApi({ agentRefreshCompletesMs: 0 });
    const list = vi.spyOn(api, "listDashboardRefreshes").mockRejectedValue(new Error("boom"));
    await mount(api);
    await flush();
    expect(latest?.refreshing).toBe(true); // the fixture ships a running agent refresh

    for (let index = 0; index < REFRESH_POLL_MAX_FAILURES; index += 1) {
      await act(async () => {
        vi.advanceTimersByTime(REFRESH_POLL_MS);
      });
      await flush();
    }
    expect(list).toHaveBeenCalledTimes(REFRESH_POLL_MAX_FAILURES);
    expect(latest?.pollError).toBe(POLL_STOPPED_MESSAGE);
    expect(latest?.refreshing).toBe(false);

    // The timer is gone: more time brings no more calls.
    await act(async () => {
      vi.advanceTimersByTime(REFRESH_POLL_MS * 5);
    });
    await flush();
    expect(list).toHaveBeenCalledTimes(REFRESH_POLL_MAX_FAILURES);

    // A reload clears the error and, with the refresh still running, resumes polling.
    list.mockRestore();
    await act(async () => {
      await latest!.reload();
    });
    expect(latest?.pollError).toBeNull();
    expect(latest?.refreshing).toBe(true);
  });

  it("stops on the first 403 and clears its timer on unmount", async () => {
    const api = createFixtureDashboardsApi({ agentRefreshCompletesMs: 0 });
    const list = vi
      .spyOn(api, "listDashboardRefreshes")
      .mockRejectedValue(new ApiRequestError(403, "forbidden"));
    await mount(api);
    await flush();
    await act(async () => {
      vi.advanceTimersByTime(REFRESH_POLL_MS);
    });
    await flush();
    expect(list).toHaveBeenCalledTimes(1);
    expect(latest?.pollError).toBe(POLL_STOPPED_MESSAGE);

    // Fresh mount, then unmount while polling: no timer survives.
    list.mockRestore();
    const detail = vi.spyOn(api, "getDashboard");
    const polling = vi.spyOn(api, "listDashboardRefreshes");
    await act(async () => root.unmount());
    root = createRoot(container);
    await mount(api);
    await flush();
    expect(detail).toHaveBeenCalledTimes(1);
    await act(async () => root.unmount());
    root = createRoot(container);
    await act(async () => {
      vi.advanceTimersByTime(REFRESH_POLL_MS * 3);
    });
    await flush();
    expect(polling).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("reports a 404 as not found", async () => {
    const api = createFixtureDashboardsApi({ agentRefreshCompletesMs: 0 });
    await mount(api, "no-such-dashboard");
    await flush();
    expect(latest?.state).toEqual({ phase: "error", message: expect.stringMatching(/not found/i), notFound: true });
  });
});

describe("pollShouldStop", () => {
  it("stops on auth and not-found statuses at once, otherwise after the budget", () => {
    expect(pollShouldStop(new ApiRequestError(401, "x"), 1)).toBe(true);
    expect(pollShouldStop(new ApiRequestError(403, "x"), 1)).toBe(true);
    expect(pollShouldStop(new ApiRequestError(404, "x"), 1)).toBe(true);
    expect(pollShouldStop(new ApiRequestError(500, "x"), 1)).toBe(false);
    expect(pollShouldStop(new Error("network"), REFRESH_POLL_MAX_FAILURES - 1)).toBe(false);
    expect(pollShouldStop(new Error("network"), REFRESH_POLL_MAX_FAILURES)).toBe(true);
  });
});

// Keep the fixture helper referenced so a future rename of the export is caught here.
void fixtureDetail;
