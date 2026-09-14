import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ConversationFileInfo } from "~/lib/api";
import { ChatUiContext, type ChatUiContextValue } from "~/components/chat/chat-ui-context";
import {
  DASHBOARD_MONTHLY_CSV_FILE,
  DASHBOARD_REGION_CSV_FILE,
  DASHBOARD_SPEC_FILE,
  DASHBOARD_SUMMARY_CSV_FILE,
  FIXTURE_DASHBOARD_FILE_ID,
  FIXTURE_DASHBOARD_MONTHLY_FILE_ID,
  FIXTURE_DASHBOARD_REGION_FILE_ID,
  FIXTURE_DASHBOARD_SUMMARY_FILE_ID,
  FIXTURE_LOADED_DASHBOARD_SLUG,
  FIXTURE_PUBLISHED_DASHBOARD_ID,
  FIXTURE_PUBLISHED_DASHBOARD_NAME,
  FIXTURE_PUBLISHED_SLUG,
  createFixtureDashboardPublishApi,
} from "~/lib/chat-test-fixture-dashboard";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// The real renderer mounts ECharts; jsdom has no layout, so stand in a
// probe that echoes what the view handed it. The view's own logic (parse,
// resolve, fetch, pending) is what these tests cover.
vi.mock("~/dashboard-renderer", async () => {
  const actual = await vi.importActual<typeof import("~/dashboard-renderer")>(
    "~/dashboard-renderer",
  );
  return {
    ...actual,
    DashboardRenderer: (props: {
      spec: { title: string; charts: { id: string }[] };
      datasets: Record<string, unknown[]>;
      theme?: string;
      onFilterStateChange?: (state: Record<string, unknown>) => void;
    }) => (
      <div
        data-testid="renderer-probe"
        data-theme={props.theme}
        data-datasets={Object.keys(props.datasets).sort().join(",")}
        data-rows={Object.values(props.datasets)
          .map((rows) => rows.length)
          .join(",")}
      >
        <h2>{props.spec.title}</h2>
        <button
          type="button"
          data-testid="probe-filter"
          onClick={() => props.onFilterStateChange?.({ regions: ["North"] })}
        >
          filter
        </button>
      </div>
    ),
  };
});

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

import { DashboardFileView, parseDashboardFile, resolveDashboardTheme } from "./dashboard-file-view";

const file = (
  id: string,
  path: string,
  kind: ConversationFileInfo["kind"],
): ConversationFileInfo => ({
  id,
  path,
  filename: path.split("/").pop() ?? path,
  kind,
  mime_type: null,
  byte_size: 10,
  content_hash: `${id}-h1`,
  origin_run_id: "run-1",
  origin: "runtime",
  status: "active",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
});

const DASHBOARD = file(FIXTURE_DASHBOARD_FILE_ID, "artifacts/revenue.dashboard.json", "dashboard");
const SUMMARY = file(FIXTURE_DASHBOARD_SUMMARY_FILE_ID, "artifacts/datasets/summary.csv", "data");
const MONTHLY = file(FIXTURE_DASHBOARD_MONTHLY_FILE_ID, "artifacts/datasets/revenue_monthly.csv", "data");
const REGION = file(FIXTURE_DASHBOARD_REGION_FILE_ID, "artifacts/datasets/revenue_by_region.csv", "data");
const ALL_FILES = [DASHBOARD, SUMMARY, MONTHLY, REGION];

const TEXTS: Record<string, string> = {
  [FIXTURE_DASHBOARD_SUMMARY_FILE_ID]: DASHBOARD_SUMMARY_CSV_FILE,
  [FIXTURE_DASHBOARD_MONTHLY_FILE_ID]: DASHBOARD_MONTHLY_CSV_FILE,
  [FIXTURE_DASHBOARD_REGION_FILE_ID]: DASHBOARD_REGION_CSV_FILE,
};

describe("parseDashboardFile", () => {
  it("returns the spec for a valid file", () => {
    const parsed = parseDashboardFile(DASHBOARD_SPEC_FILE);
    expect(parsed.errors).toBeNull();
    expect(parsed.spec?.title).toBe("Revenue overview 2024");
  });
  it("lists JSON and schema errors", () => {
    expect(parseDashboardFile("{not json").errors?.[0]).toMatch(/not valid JSON/);
    const invalid = parseDashboardFile(JSON.stringify({ version: 1, charts: [] }));
    expect(invalid.spec).toBeNull();
    expect(invalid.errors?.length).toBeGreaterThan(0);
  });
});

describe("resolveDashboardTheme", () => {
  it("is dark unless the root opts into light", () => {
    const root = document.createElement("html");
    expect(resolveDashboardTheme(root)).toBe("dark");
    root.dataset.theme = "light";
    expect(resolveDashboardTheme(root)).toBe("light");
    delete root.dataset.theme;
    root.classList.add("light");
    expect(resolveDashboardTheme(root)).toBe("light");
    expect(resolveDashboardTheme(null)).toBe("dark");
  });
});

describe("DashboardFileView", () => {
  let container: HTMLDivElement;
  let root: Root;
  const getFileText = vi.fn(async (fileId: string) => {
    const text = TEXTS[fileId];
    if (text === undefined) throw new Error(`no text for ${fileId}`);
    return text;
  });
  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    getFileText.mockClear();
  });
  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (
    props: {
      text?: string;
      files?: ConversationFileInfo[];
      running?: boolean;
      publishApi?: ReturnType<typeof createFixtureDashboardPublishApi>;
    },
    ui: Partial<ChatUiContextValue> = {},
  ) => {
    const value = {
      events: [],
      conversationId: "conv-1",
      files: props.files ?? [],
      openArtifact: () => undefined,
      getFileText,
      onStop: async () => undefined,
      onRetry: async () => undefined,
      ...ui,
    } as ChatUiContextValue;
    await act(async () => {
      root.render(
        <ChatUiContext.Provider value={value}>
          <DashboardFileView
            file={DASHBOARD}
            text={props.text ?? DASHBOARD_SPEC_FILE}
            files={props.files ?? []}
            running={props.running ?? false}
            publishApi={props.publishApi ?? createFixtureDashboardPublishApi()}
          />
        </ChatUiContext.Provider>,
      );
    });
  };
  const q = (selector: string) => container.querySelector(selector);
  /** Set a controlled input/select through the native setter so React sees it. */
  const setField = async (selector: string, value: string) => {
    const element = document.querySelector<HTMLInputElement | HTMLSelectElement>(selector);
    if (!element) throw new Error(`missing ${selector}`);
    const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(element) as object, "value")?.set;
    await act(async () => {
      setter?.call(element, value);
      element.dispatchEvent(new Event(element instanceof HTMLSelectElement ? "change" : "input", { bubbles: true }));
    });
  };
  /** Poll for an element that appears after an async effect settles. */
  const waitForEl = async (selector: string, attempts = 50) => {
    for (let i = 0; i < attempts; i += 1) {
      const found = q(selector);
      if (found) return found;
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 10));
      });
    }
    throw new Error(`Timed out waiting for ${selector}`);
  };

  it("fetches every SQL dataset's snapshot by convention path and renders once they land", async () => {
    await render({ files: ALL_FILES });
    const probe = q('[data-testid="renderer-probe"]');
    expect(probe).not.toBeNull();
    expect(probe?.getAttribute("data-datasets")).toBe("revenue_by_region,revenue_monthly,summary");
    expect(probe?.getAttribute("data-rows")).toBe("1,48,4");
    expect(probe?.getAttribute("data-theme")).toBe("dark");
    expect(probe?.textContent).toContain("Revenue overview 2024");
    expect(getFileText).toHaveBeenCalledTimes(3);
    expect(getFileText.mock.calls.map((call) => call[0]).sort()).toEqual(
      [FIXTURE_DASHBOARD_MONTHLY_FILE_ID, FIXTURE_DASHBOARD_REGION_FILE_ID, FIXTURE_DASHBOARD_SUMMARY_FILE_ID].sort(),
    );
    expect(q('[data-testid="chat-dashboard-view"]')?.getAttribute("data-pending")).toBe("0");
    expect(q('[data-testid="chat-dashboard-expand"]')).not.toBeNull();
    expect(q('[data-testid="chat-dashboard-download"]')?.textContent).toContain("Download JSON");
  });

  it("shows the pending shimmer while a snapshot is unresolved and the run streams", async () => {
    await render({ files: [DASHBOARD, SUMMARY, MONTHLY], running: true });
    expect(q('[data-testid="chat-md-figure-pending"]')).not.toBeNull();
    expect(q('[data-testid="renderer-probe"]')).toBeNull();
    expect(q('[data-testid="chat-dashboard-view"]')?.getAttribute("data-pending")).toBe("1");
  });

  it("renders with the snapshots it has once the run is over", async () => {
    await render({ files: [DASHBOARD, SUMMARY, MONTHLY], running: false });
    const probe = q('[data-testid="renderer-probe"]');
    expect(probe).not.toBeNull();
    // The region snapshot is missing: it stays out of the map so the
    // renderer reports snapshot_missing per tile.
    expect(probe?.getAttribute("data-datasets")).toBe("revenue_monthly,summary");
    expect(q('[data-testid="chat-md-figure-pending"]')).toBeNull();
  });

  it("owns the filter state handed back by the renderer", async () => {
    await render({ files: ALL_FILES });
    await act(async () => (q('[data-testid="probe-filter"]') as HTMLButtonElement).click());
    // No crash and the renderer is still mounted with the same datasets.
    expect(q('[data-testid="renderer-probe"]')?.getAttribute("data-rows")).toBe("1,48,4");
  });

  it("shows the error band with a raw toggle for invalid JSON and invalid specs", async () => {
    await render({ text: "{oops" });
    const band = q('[data-testid="chat-dashboard-errors"]');
    expect(band?.textContent).toContain("not valid JSON");
    expect(q('[data-testid="renderer-probe"]')).toBeNull();
    expect(q('[data-testid="chat-dashboard-expand"]')).toBeNull();
    expect(q(".chat-code, pre")).toBeNull();
    await act(async () => (q('[data-testid="chat-dashboard-show-raw"]') as HTMLButtonElement).click());
    expect(container.textContent).toContain("{oops");

    await render({ text: JSON.stringify({ version: 1, title: "x" }) });
    expect(q('[data-testid="chat-dashboard-errors"]')?.textContent).toContain("cannot be rendered");
  });

  it("opens the expanded overlay from the header action", async () => {
    await render({ files: ALL_FILES });
    await act(async () => (q('[data-testid="chat-dashboard-expand"]') as HTMLButtonElement).click());
    const lightbox = document.querySelector('[data-testid="artifact-lightbox"]');
    expect(lightbox).not.toBeNull();
    expect(lightbox?.querySelector('[data-testid="chat-dashboard-expanded"] [data-testid="renderer-probe"]')).not.toBeNull();
    expect(lightbox?.textContent).toContain("Revenue overview 2024");
  });

  it("offers Publish next to Expand and opens the dialog prefilled", async () => {
    // A gallery with no slug match, so the form fills from the spec.
    const publishApi = createFixtureDashboardPublishApi();
    const original = publishApi.listDashboards.bind(publishApi);
    publishApi.listDashboards = async () => {
      const { dashboards } = await original();
      return { dashboards: dashboards.map((dashboard) => ({ ...dashboard, slug: "pipeline" })) };
    };
    await render({ files: ALL_FILES, publishApi });
    const header = q('[data-testid="chat-dashboard-expand"]')?.parentElement;
    const publish = header?.querySelector('[data-testid="chat-dashboard-publish"]');
    expect(publish?.textContent).toContain("Publish");
    expect(q('[data-testid="chat-dashboard-published"]')).toBeNull();
    expect(q('[data-testid="chat-dashboard-loaded"]')).toBeNull();
    await act(async () => (publish as HTMLButtonElement).click());
    const dialog = document.querySelector('[data-testid="chat-dashboard-publish-dialog"]');
    expect(dialog).not.toBeNull();
    expect(
      dialog?.querySelector<HTMLInputElement>('[data-testid="chat-dashboard-publish-name"]')?.value,
    ).toBe("Revenue overview 2024");
    expect(dialog?.querySelectorAll('[data-testid="chat-dashboard-publish-dataset"]').length).toBe(3);
  });

  it("hides Publish for an invalid spec", async () => {
    await render({ text: "{oops" });
    expect(q('[data-testid="chat-dashboard-publish"]')).toBeNull();
  });

  it("shows the published strip after a successful publish", async () => {
    const publishApi = createFixtureDashboardPublishApi();
    await render({ files: ALL_FILES, publishApi });
    await act(async () => (q('[data-testid="chat-dashboard-publish"]') as HTMLButtonElement).click());
    // The file stem matches the fixture gallery's slug, so the dialog opens
    // on that dashboard; this publish is a fresh one under the spec's title.
    await setField('[data-testid="chat-dashboard-publish-target"]', "new");
    await setField('[data-testid="chat-dashboard-publish-name"]', "Revenue overview 2024");
    await act(async () => {
      document
        .querySelector<HTMLButtonElement>('[data-testid="chat-dashboard-publish-submit"]')
        ?.click();
    });
    expect(document.querySelector('[data-testid="chat-dashboard-publish-dialog"]')).toBeNull();
    const strip = q('[data-testid="chat-dashboard-published"]');
    expect(strip?.textContent).toContain("Published as Revenue overview 2024");
    expect(strip?.querySelector("a")?.getAttribute("href")).toBe(`/dashboards/${FIXTURE_PUBLISHED_SLUG}`);
    expect(publishApi.calls[0].fileId).toBe(FIXTURE_DASHBOARD_FILE_ID);
    expect(publishApi.calls[0].body.target_dashboard_id).toBeUndefined();
    // The publish from this file now wins over the slug match.
    expect(q('[data-testid="chat-dashboard-loaded"]')).toBeNull();
    // "Publish new version" reopens the dialog on that dashboard.
    await act(async () => (q('[data-testid="chat-dashboard-publish-version"]') as HTMLButtonElement).click());
    expect(
      document.querySelector<HTMLSelectElement>('[data-testid="chat-dashboard-publish-target"]')?.value,
    ).toBe("dash_fixture_published");
  });

  it("shows the already-published state on mount when the gallery has this file", async () => {
    const publishApi = createFixtureDashboardPublishApi();
    const original = publishApi.listDashboards.bind(publishApi);
    publishApi.listDashboards = async () => {
      const { dashboards } = await original();
      return {
        dashboards: dashboards.map((dashboard) => ({
          ...dashboard,
          source_conversation_id: "conv-1",
          source_file_id: FIXTURE_DASHBOARD_FILE_ID,
        })),
      };
    };
    await render({ files: ALL_FILES, publishApi });
    const strip = await waitForEl('[data-testid="chat-dashboard-published"]');
    expect(strip.getAttribute("data-dashboard-slug")).toBe(FIXTURE_LOADED_DASHBOARD_SLUG);
    expect(q('[data-testid="chat-dashboard-loaded"]')).toBeNull();
    // The header Publish targets the existing dashboard.
    await act(async () => (q('[data-testid="chat-dashboard-publish"]') as HTMLButtonElement).click());
    expect(
      document.querySelector<HTMLSelectElement>('[data-testid="chat-dashboard-publish-target"]')?.value,
    ).toBe(FIXTURE_PUBLISHED_DASHBOARD_ID);
  });

  it("shows where the file was loaded from and preselects that dashboard", async () => {
    await render({ files: ALL_FILES });
    const strip = await waitForEl('[data-testid="chat-dashboard-loaded"]');
    expect(strip.getAttribute("data-dashboard-slug")).toBe(FIXTURE_LOADED_DASHBOARD_SLUG);
    expect(strip.textContent).toContain(`Loaded from ${FIXTURE_PUBLISHED_DASHBOARD_NAME}`);
    expect(strip.textContent).toContain("(v3)");
    expect(strip.querySelector('[data-testid="chat-dashboard-loaded-open"]')?.getAttribute("href")).toBe(
      `/dashboards/${FIXTURE_LOADED_DASHBOARD_SLUG}`,
    );
    expect(q('[data-testid="chat-dashboard-published"]')).toBeNull();
    // Both the header Publish and the strip action open on that dashboard.
    await act(async () => (q('[data-testid="chat-dashboard-publish"]') as HTMLButtonElement).click());
    const target = () => document.querySelector<HTMLSelectElement>('[data-testid="chat-dashboard-publish-target"]');
    expect(target()?.value).toBe(FIXTURE_PUBLISHED_DASHBOARD_ID);
    expect(document.querySelector('[data-testid="chat-dashboard-publish-name"]')?.getAttribute("value")).toBe(
      FIXTURE_PUBLISHED_DASHBOARD_NAME,
    );
    await act(async () => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    });
    expect(document.querySelector('[data-testid="chat-dashboard-publish-dialog"]')).toBeNull();
    await act(async () => (q('[data-testid="chat-dashboard-publish-version"]') as HTMLButtonElement).click());
    expect(target()?.value).toBe(FIXTURE_PUBLISHED_DASHBOARD_ID);
  });
});
