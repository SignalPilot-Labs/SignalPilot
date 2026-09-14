"use client";

// Fixture surface for /dashboards/test: the gallery and the detail page
// against the in-memory API, with links rewritten to stay on the test page.
// Entry points for Playwright:
//   /dashboards/test                    the gallery
//   /dashboards/test?view=detail        the fixture dashboard

import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { createFixtureDashboardsApi } from "~/lib/dashboards/fixture-api";
import { FIXTURE_DASHBOARD_SLUG, FIXTURE_NOW } from "~/lib/dashboards/fixture";

import { DashboardGallery } from "./dashboard-gallery";
import { DashboardPage } from "./dashboard-page";
import { DashboardsApiProvider } from "./dashboards-api-context";

const BASE = "/dashboards/test";

const routes = {
  gallery: BASE,
  dashboard: (slug: string) => `${BASE}?view=detail&slug=${encodeURIComponent(slug)}`,
  chat: (conversationId: string) => `/chats/${encodeURIComponent(conversationId)}`,
};

const now = () => FIXTURE_NOW;

export function DashboardsTestHarness() {
  const params = useSearchParams();
  const view = params.get("view") ?? "gallery";
  const slug = params.get("slug") ?? FIXTURE_DASHBOARD_SLUG;
  const latencyMs = Math.max(0, Number(params.get("latency")) || 0);
  const api = useMemo(() => createFixtureDashboardsApi({ latencyMs, refreshDurationMs: 1_500 }), [latencyMs]);
  // Click-based specs gate on this: a click before hydration is lost.
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => setHydrated(true), []);

  return (
    <div data-testid="dashboards-test-harness" data-hydrated={hydrated ? "1" : "0"} data-view={view}>
      <DashboardsApiProvider api={api} routes={routes} now={now}>
        {view === "detail" ? <DashboardPage key={slug} idOrSlug={slug} /> : <DashboardGallery />}
      </DashboardsApiProvider>
    </div>
  );
}
