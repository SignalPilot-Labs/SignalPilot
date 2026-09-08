import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ConversationFileInfo } from "~/lib/api";
import { ApiRequestError } from "~/lib/api/client";
import type { PublishDashboardRequest, PublishedDashboard } from "~/lib/api/dashboards";
import {
  DASHBOARD_SPEC_FILE,
  FIXTURE_DASHBOARD_FILE_ID,
  FIXTURE_DASHBOARD_MONTHLY_FILE_ID,
  FIXTURE_DASHBOARD_REGION_FILE_ID,
  FIXTURE_PUBLISHED_DASHBOARD_ID,
  FIXTURE_PUBLISHED_DASHBOARD_NAME,
  FIXTURE_PUBLISHED_SLUG,
  createFixtureDashboardPublishApi,
} from "~/lib/chat-test-fixture-dashboard";
import { validateDashboardSpec, type DashboardSpec } from "~/dashboard-renderer";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

import { DashboardPublishDialog, DashboardPublishedStrip } from "./dashboard-publish-dialog";
import {
  buildPublishRequest,
  describePublishError,
  findPublishedDashboard,
  initialPublishForm,
  publishDatasetRows,
  retargetPublishForm,
} from "./dashboard-publish-form";

const file = (id: string, path: string, kind: ConversationFileInfo["kind"]): ConversationFileInfo => ({
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
const ALL_FILES = [DASHBOARD, MONTHLY, REGION];

function spec(): DashboardSpec {
  const result = validateDashboardSpec(JSON.parse(DASHBOARD_SPEC_FILE));
  if (!result.ok) throw new Error(result.errors.join("\n"));
  return result.spec;
}

describe("publish form model", () => {
  it("prefills from the spec with the daily default in the given zone", () => {
    const form = initialPublishForm(spec(), { timezone: "Europe/Paris" });
    expect(form).toMatchObject({
      name: "Revenue overview 2024",
      target: "new",
      description: "Monthly revenue by region with targets, share of revenue and customer economics.",
      visibility: "org",
      intervalMinutes: 1440,
      anchorTime: "06:00",
      timezone: "Europe/Paris",
      mode: "sql",
      notifyOnFailure: true,
    });
  });

  it("builds the exact PublishDashboardRequest body", () => {
    const form = initialPublishForm(spec(), { timezone: "America/New_York" });
    const body: PublishDashboardRequest = buildPublishRequest({ ...form, name: "  Revenue  " });
    expect(body).toStrictEqual({
      name: "Revenue",
      description: "Monthly revenue by region with targets, share of revenue and customer economics.",
      visibility: "org",
      refresh: { interval_minutes: 1440, anchor_time: "06:00", timezone: "America/New_York", mode: "sql" },
      notify_on_failure: true,
    });
    const off = buildPublishRequest({ ...form, description: "  ", intervalMinutes: null, target: "dash_1" });
    expect(off).toStrictEqual({
      name: "Revenue overview 2024",
      visibility: "org",
      refresh: { interval_minutes: null, anchor_time: "06:00", timezone: "America/New_York", mode: "sql" },
      notify_on_failure: true,
      target_dashboard_id: "dash_1",
    });
  });

  it("classifies datasets by source and resolves their files", () => {
    const rows = publishDatasetRows(spec(), [DASHBOARD, MONTHLY], { runId: "run-1" });
    expect(rows.map((row) => [row.name, row.refreshable, row.status])).toEqual([
      ["summary", false, "inline"],
      ["revenue_monthly", false, "found"],
      ["revenue_by_region", true, "missing"],
    ]);
  });

  it("adopts the target dashboard's settings on retarget", async () => {
    const api = createFixtureDashboardPublishApi();
    const { dashboards } = await api.listDashboards();
    const form = retargetPublishForm(initialPublishForm(spec()), FIXTURE_PUBLISHED_DASHBOARD_ID, dashboards);
    expect(form.target).toBe(FIXTURE_PUBLISHED_DASHBOARD_ID);
    expect(form.name).toBe(FIXTURE_PUBLISHED_DASHBOARD_NAME);
    expect(form.timezone).toBe("America/New_York");
    expect(findPublishedDashboard(dashboards, "conversation-fixture-0", "file-fixture-other")?.id).toBe(
      FIXTURE_PUBLISHED_DASHBOARD_ID,
    );
    expect(findPublishedDashboard(dashboards, "conversation-x", "file-fixture-other")).toBeNull();
  });

  it("describes gateway failures with their status and missing names", () => {
    const missing = describePublishError(
      new ApiRequestError(422, JSON.stringify({ detail: { message: "Dataset files not found", missing_datasets: ["a", "b"] } })),
    );
    expect(missing).toEqual({ status: 422, missing: ["a", "b"], message: "Dataset files not found Missing: a, b." });
    expect(describePublishError(new ApiRequestError(409, JSON.stringify({ detail: "Slug taken" }))).message).toBe("Slug taken");
    expect(describePublishError(new ApiRequestError(409, "")).message).toMatch(/name is taken/);
    expect(describePublishError(new Error("boom")).message).toBe("boom");
  });
});

describe("DashboardPublishDialog", () => {
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
  const q = <T extends Element = HTMLElement>(selector: string) => document.querySelector<T>(selector);

  const render = async (props: {
    files?: ConversationFileInfo[];
    api: ReturnType<typeof createFixtureDashboardPublishApi>;
    dashboards?: PublishedDashboard[];
    initialTargetId?: string | null;
    onPublished?: (result: { dashboard: PublishedDashboard }) => void;
    onClose?: () => void;
  }) => {
    await act(async () => {
      root.render(
        <DashboardPublishDialog
          open
          onClose={props.onClose ?? (() => undefined)}
          conversationId="conv-1"
          file={DASHBOARD}
          spec={spec()}
          files={props.files ?? ALL_FILES}
          dashboards={props.dashboards ?? []}
          initialTargetId={props.initialTargetId ?? null}
          onPublished={props.onPublished ?? (() => undefined)}
          api={props.api}
          timezone="Europe/London"
        />,
      );
    });
  };

  const setValue = async (selector: string, value: string) => {
    const element = q<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>(selector);
    if (!element) throw new Error(`missing ${selector}`);
    const proto = Object.getPrototypeOf(element) as object;
    const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
    await act(async () => {
      setter?.call(element, value);
      element.dispatchEvent(new Event(element instanceof HTMLSelectElement ? "change" : "input", { bubbles: true }));
    });
  };

  it("prefills from the spec and lists the datasets", async () => {
    const api = createFixtureDashboardPublishApi();
    await render({ api });
    expect(q<HTMLInputElement>('[data-testid="chat-dashboard-publish-name"]')?.value).toBe("Revenue overview 2024");
    expect(q<HTMLTextAreaElement>('[data-testid="chat-dashboard-publish-description"]')?.value).toMatch(/^Monthly revenue/);
    expect(q<HTMLSelectElement>('[data-testid="chat-dashboard-publish-interval"]')?.value).toBe("1440");
    expect(q<HTMLInputElement>('[data-testid="chat-dashboard-publish-anchor"]')?.value).toBe("06:00");
    expect(q<HTMLInputElement>('[data-testid="chat-dashboard-publish-timezone"]')?.value).toBe("Europe/London");
    const rows = document.querySelectorAll('[data-testid="chat-dashboard-publish-dataset"]');
    expect(rows.length).toBe(3);
    expect(rows[2].textContent).toContain("Refreshable (SQL)");
    expect(rows[1].textContent).toContain("Static snapshot");
    expect(rows[1].getAttribute("data-status")).toBe("found");
    expect(q('[data-testid="chat-dashboard-publish-error"]')).toBeNull();
    expect(q<HTMLButtonElement>('[data-testid="chat-dashboard-publish-submit"]')?.disabled).toBe(false);
  });

  it("disables submit while a file-backed dataset is missing and says why", async () => {
    const api = createFixtureDashboardPublishApi();
    await render({ api, files: [DASHBOARD, MONTHLY] });
    const row = q('[data-testid="chat-dashboard-publish-dataset"][data-dataset="revenue_by_region"]');
    expect(row?.getAttribute("data-status")).toBe("missing");
    expect(q<HTMLButtonElement>('[data-testid="chat-dashboard-publish-submit"]')?.disabled).toBe(true);
    expect(q('[data-testid="chat-dashboard-publish-error"]')?.textContent).toContain("artifacts/revenue_by_region.json");
    await act(async () => q<HTMLButtonElement>('[data-testid="chat-dashboard-publish-submit"]')?.click());
    expect(api.calls).toHaveLength(0);
  });

  it("submits the exact request body and reports the result", async () => {
    const api = createFixtureDashboardPublishApi();
    const onPublished = vi.fn();
    await render({ api, onPublished });
    await setValue('[data-testid="chat-dashboard-publish-name"]', "Revenue 2024");
    await setValue('[data-testid="chat-dashboard-publish-interval"]', "240");
    await setValue('[data-testid="chat-dashboard-publish-anchor"]', "08:30");
    await act(async () => q<HTMLInputElement>('[data-testid="chat-dashboard-publish-notify"]')?.click());
    await act(async () => q<HTMLButtonElement>('[data-testid="chat-dashboard-publish-submit"]')?.click());
    expect(api.calls).toHaveLength(1);
    expect(api.calls[0].conversationId).toBe("conv-1");
    expect(api.calls[0].fileId).toBe(FIXTURE_DASHBOARD_FILE_ID);
    expect(api.calls[0].body).toStrictEqual({
      name: "Revenue 2024",
      description: "Monthly revenue by region with targets, share of revenue and customer economics.",
      visibility: "org",
      refresh: { interval_minutes: 240, anchor_time: "08:30", timezone: "Europe/London", mode: "sql" },
      notify_on_failure: false,
    });
    expect(onPublished).toHaveBeenCalledTimes(1);
    expect(onPublished.mock.calls[0][0].dashboard.slug).toBe(FIXTURE_PUBLISHED_SLUG);
  });

  it("offers editable dashboards as targets and sets target_dashboard_id", async () => {
    const api = createFixtureDashboardPublishApi();
    const { dashboards } = await api.listDashboards();
    const readOnly: PublishedDashboard = { ...dashboards[0], id: "dash_locked", name: "Locked", can_edit: false };
    await render({ api, dashboards: [...dashboards, readOnly] });
    const target = q<HTMLSelectElement>('[data-testid="chat-dashboard-publish-target"]');
    expect(Array.from(target?.options ?? []).map((option) => option.textContent)).toEqual([
      "New dashboard",
      FIXTURE_PUBLISHED_DASHBOARD_NAME,
    ]);
    await setValue('[data-testid="chat-dashboard-publish-target"]', FIXTURE_PUBLISHED_DASHBOARD_ID);
    expect(q<HTMLInputElement>('[data-testid="chat-dashboard-publish-name"]')?.value).toBe(FIXTURE_PUBLISHED_DASHBOARD_NAME);
    expect(q('[role="dialog"]')?.textContent).toContain("Publish a new version");
    await act(async () => q<HTMLButtonElement>('[data-testid="chat-dashboard-publish-submit"]')?.click());
    expect(api.calls[0].body.target_dashboard_id).toBe(FIXTURE_PUBLISHED_DASHBOARD_ID);
    expect(api.calls[0].body.refresh.timezone).toBe("America/New_York");
  });

  it("preselects the target for a new version", async () => {
    const api = createFixtureDashboardPublishApi();
    const { dashboards } = await api.listDashboards();
    await render({ api, dashboards, initialTargetId: FIXTURE_PUBLISHED_DASHBOARD_ID });
    expect(q<HTMLSelectElement>('[data-testid="chat-dashboard-publish-target"]')?.value).toBe(FIXTURE_PUBLISHED_DASHBOARD_ID);
    expect(q<HTMLButtonElement>('[data-testid="chat-dashboard-publish-submit"]')?.textContent).toContain("Publish version");
  });

  it("renders gateway errors inline and keeps the form", async () => {
    const api = createFixtureDashboardPublishApi();
    api.publishDashboard = async () => {
      throw new ApiRequestError(422, JSON.stringify({ detail: { message: "Dataset files not found", missing_datasets: ["revenue_by_region"] } }));
    };
    const onPublished = vi.fn();
    await render({ api, onPublished });
    await act(async () => q<HTMLButtonElement>('[data-testid="chat-dashboard-publish-submit"]')?.click());
    expect(onPublished).not.toHaveBeenCalled();
    expect(q('[data-testid="chat-dashboard-publish-api-error"]')?.textContent).toContain("revenue_by_region");
    expect(q<HTMLButtonElement>('[data-testid="chat-dashboard-publish-submit"]')?.disabled).toBe(false);
    expect(q<HTMLInputElement>('[data-testid="chat-dashboard-publish-name"]')?.value).toBe("Revenue overview 2024");
  });

  it("closes on Escape", async () => {
    const api = createFixtureDashboardPublishApi();
    const onClose = vi.fn();
    await render({ api, onClose });
    await act(async () => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe("DashboardPublishedStrip", () => {
  it("names the dashboard, links to it, and offers a new version", async () => {
    const api = createFixtureDashboardPublishApi();
    const { dashboards } = await api.listDashboards();
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    const onPublishNewVersion = vi.fn();
    await act(async () => {
      root.render(<DashboardPublishedStrip dashboard={dashboards[0]} onPublishNewVersion={onPublishNewVersion} />);
    });
    const strip = container.querySelector('[data-testid="chat-dashboard-published"]');
    expect(strip?.textContent).toContain(`Published as ${FIXTURE_PUBLISHED_DASHBOARD_NAME}`);
    expect(strip?.textContent).toContain("v3");
    expect(container.querySelector('[data-testid="chat-dashboard-published-open"]')?.getAttribute("href")).toBe(
      "/dashboards/weekly-pipeline-health",
    );
    await act(async () => (container.querySelector('[data-testid="chat-dashboard-publish-version"]') as HTMLButtonElement).click());
    expect(onPublishNewVersion).toHaveBeenCalledTimes(1);
    await act(async () => root.unmount());
    container.remove();
  });
});
