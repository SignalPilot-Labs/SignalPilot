import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { UpdateDashboardRequest } from "~/lib/api/dashboards";
import { fixtureDashboard } from "~/lib/dashboards/fixture";

import { DashboardSettingsDrawer, requestFromDraft, draftFromDashboard, validateDraft } from "./dashboard-settings-drawer";

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

// The drawer portals into document.body, so query the document, not the root.
const query = <T extends Element>(selector: string) => {
  const element = document.querySelector<T>(selector);
  if (!element) throw new Error(`Missing ${selector}`);
  return element;
};

function setValue(element: HTMLSelectElement | HTMLInputElement, value: string) {
  // React listens on the native value setter; bypass the instance tracker.
  const proto = Object.getPrototypeOf(element) as object;
  const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
  setter?.call(element, value);
  element.dispatchEvent(new Event("change", { bubbles: true }));
  element.dispatchEvent(new Event("input", { bubbles: true }));
}

describe("DashboardSettingsDrawer", () => {
  it("updates the schedule preview when the interval changes", async () => {
    await act(async () => {
      root.render(
        <DashboardSettingsDrawer
          open
          dashboard={fixtureDashboard()}
          onClose={() => {}}
          onSubmit={async () => {}}
        />,
      );
    });
    const preview = query('[data-testid="dashboard-settings-preview"]');
    expect(preview.textContent).toContain("Daily at 06:00 ET");
    const select = query<HTMLSelectElement>('[data-testid="dashboard-settings-interval"]');
    await act(async () => setValue(select, "240"));
    expect(preview.textContent).toContain("Every 4 hours");
    await act(async () => setValue(select, ""));
    expect(preview.textContent).toContain("Off");
  });

  it("submits the exact refresh shape and closes", async () => {
    const onSubmit = vi.fn(async (_body: UpdateDashboardRequest) => {});
    const onClose = vi.fn();
    await act(async () => {
      root.render(
        <DashboardSettingsDrawer open dashboard={fixtureDashboard()} onClose={onClose} onSubmit={onSubmit} />,
      );
    });
    await act(async () =>
      setValue(query<HTMLSelectElement>('[data-testid="dashboard-settings-interval"]'), "240"),
    );
    await act(async () =>
      setValue(query<HTMLInputElement>('[data-testid="dashboard-settings-anchor"]'), "07:30"),
    );
    await act(async () =>
      setValue(query<HTMLSelectElement>('[data-testid="dashboard-settings-timezone"]'), "Europe/Berlin"),
    );
    await act(async () => {
      query<HTMLButtonElement>('[data-testid="dashboard-settings-notify"]').click();
    });
    await act(async () => {
      query<HTMLFormElement>("form").requestSubmit();
    });
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit.mock.calls[0][0]).toEqual({
      name: "Revenue overview 2024",
      description: "Monthly revenue by region with targets, share of revenue and customer economics.",
      visibility: "org",
      refresh: { interval_minutes: 240, anchor_time: "07:30", timezone: "Europe/Berlin", mode: "sql" },
      notify_on_failure: false,
    });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("blocks submit on a bad anchor time and shows why", async () => {
    const onSubmit = vi.fn(async () => {});
    await act(async () => {
      root.render(
        <DashboardSettingsDrawer open dashboard={fixtureDashboard()} onClose={() => {}} onSubmit={onSubmit} />,
      );
    });
    await act(async () =>
      setValue(query<HTMLInputElement>('[data-testid="dashboard-settings-anchor"]'), "6am"),
    );
    await act(async () => {
      query<HTMLFormElement>("form").requestSubmit();
    });
    expect(onSubmit).not.toHaveBeenCalled();
    expect(query('[role="alert"]').textContent).toContain("Aligned to");
  });
});

describe("draft helpers", () => {
  it("round-trips a dashboard into a PATCH body", () => {
    const draft = draftFromDashboard(fixtureDashboard());
    expect(validateDraft(draft)).toBeNull();
    expect(requestFromDraft(draft).refresh).toEqual({
      interval_minutes: 1440,
      anchor_time: "06:00",
      timezone: "America/New_York",
      mode: "sql",
    });
    expect(requestFromDraft({ ...draft, description: "  " }).description).toBeNull();
    expect(validateDraft({ ...draft, name: " " })).toMatch(/name/);
    expect(validateDraft({ ...draft, refresh: { ...draft.refresh, timezone: "Nowhere/Land" } })).toMatch(/timezone/);
  });
});
