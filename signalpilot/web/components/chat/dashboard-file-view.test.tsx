import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ConversationFileInfo } from "~/lib/api";
import { ChatUiContext, type ChatUiContextValue } from "~/components/chat/chat-ui-context";
import {
  DASHBOARD_MONTHLY_CSV_FILE,
  DASHBOARD_REGION_JSON_FILE,
  DASHBOARD_SPEC_FILE,
  FIXTURE_DASHBOARD_FILE_ID,
  FIXTURE_DASHBOARD_MONTHLY_FILE_ID,
  FIXTURE_DASHBOARD_REGION_FILE_ID,
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
const MONTHLY = file(FIXTURE_DASHBOARD_MONTHLY_FILE_ID, "artifacts/revenue_monthly.csv", "data");
const REGION = file(FIXTURE_DASHBOARD_REGION_FILE_ID, "artifacts/revenue_by_region.json", "data");

const TEXTS: Record<string, string> = {
  [FIXTURE_DASHBOARD_MONTHLY_FILE_ID]: DASHBOARD_MONTHLY_CSV_FILE,
  [FIXTURE_DASHBOARD_REGION_FILE_ID]: DASHBOARD_REGION_JSON_FILE,
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
    props: { text?: string; files?: ConversationFileInfo[]; running?: boolean },
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
          />
        </ChatUiContext.Provider>,
      );
    });
  };
  const q = (selector: string) => container.querySelector(selector);

  it("fetches the file-backed datasets and renders once they land", async () => {
    await render({ files: [DASHBOARD, MONTHLY, REGION] });
    const probe = q('[data-testid="renderer-probe"]');
    expect(probe).not.toBeNull();
    expect(probe?.getAttribute("data-datasets")).toBe("revenue_by_region,revenue_monthly,summary");
    expect(probe?.getAttribute("data-rows")).toBe("1,48,4");
    expect(probe?.getAttribute("data-theme")).toBe("dark");
    expect(probe?.textContent).toContain("Revenue overview 2024");
    expect(getFileText).toHaveBeenCalledTimes(2);
    expect(q('[data-testid="chat-dashboard-view"]')?.getAttribute("data-pending")).toBe("0");
    expect(q('[data-testid="chat-dashboard-expand"]')).not.toBeNull();
    expect(q('[data-testid="chat-dashboard-download"]')?.textContent).toContain("Download JSON");
  });

  it("shows the pending shimmer while a dataset is unresolved and the run streams", async () => {
    await render({ files: [DASHBOARD, MONTHLY], running: true });
    expect(q('[data-testid="chat-md-figure-pending"]')).not.toBeNull();
    expect(q('[data-testid="renderer-probe"]')).toBeNull();
    expect(q('[data-testid="chat-dashboard-view"]')?.getAttribute("data-pending")).toBe("1");
  });

  it("renders with the datasets it has once the run is over", async () => {
    await render({ files: [DASHBOARD, MONTHLY], running: false });
    const probe = q('[data-testid="renderer-probe"]');
    expect(probe).not.toBeNull();
    // The region file is missing: it stays out of the map so the renderer
    // reports dataset_unreadable per tile.
    expect(probe?.getAttribute("data-datasets")).toBe("revenue_monthly,summary");
    expect(q('[data-testid="chat-md-figure-pending"]')).toBeNull();
  });

  it("owns the filter state handed back by the renderer", async () => {
    await render({ files: [DASHBOARD, MONTHLY, REGION] });
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
    await render({ files: [DASHBOARD, MONTHLY, REGION] });
    await act(async () => (q('[data-testid="chat-dashboard-expand"]') as HTMLButtonElement).click());
    const lightbox = document.querySelector('[data-testid="artifact-lightbox"]');
    expect(lightbox).not.toBeNull();
    expect(lightbox?.querySelector('[data-testid="chat-dashboard-expanded"] [data-testid="renderer-probe"]')).not.toBeNull();
    expect(lightbox?.textContent).toContain("Revenue overview 2024");
  });
});
