"use client";

// Fixture surface for /dashboards/test: the gallery, the detail page and
// the shared view against the in-memory API, with links rewritten to stay
// on the test page. Entry points for Playwright:
//   /dashboards/test                    the gallery
//   /dashboards/test?view=detail        the fixture dashboard
//   /dashboards/test?view=shared        the read-only shared view

import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { createFixtureDashboardsApi } from "~/lib/dashboards/fixture-api";
import { FIXTURE_DASHBOARD_SLUG, FIXTURE_NOW, FIXTURE_SHARE_TOKEN } from "~/lib/dashboards/fixture";

import { DashboardGallery } from "./dashboard-gallery";
import { DashboardPage } from "./dashboard-page";
import { DashboardSharedView } from "./dashboard-shared-view";
import { DashboardsApiProvider } from "./dashboards-api-context";

const BASE = "/dashboards/test";

const routes = {
  gallery: BASE,
  dashboard: (slug: string) => `${BASE}?view=detail&slug=${encodeURIComponent(slug)}`,
  chat: (conversationId: string) => `/chats/${encodeURIComponent(conversationId)}`,
  shared: (token: string) => `${BASE}?view=shared&token=${encodeURIComponent(token)}`,
};

const now = () => FIXTURE_NOW;

export function DashboardsTestHarness() {
  const params = useSearchParams();
  const view = params.get("view") ?? "gallery";
  const slug = params.get("slug") ?? FIXTURE_DASHBOARD_SLUG;
  const token = params.get("token") ?? FIXTURE_SHARE_TOKEN;
  const latencyMs = Math.max(0, Number(params.get("latency")) || 0);
  const api = useMemo(() => {
    const fixture = createFixtureDashboardsApi({ latencyMs, refreshDurationMs: 1_500 });
    // The shared view needs a link-visible dashboard; the fixture starts as "org".
    if (view === "shared") {
      const primary = fixture.state.dashboards[0];
      primary.visibility = "link";
      primary.share_token = FIXTURE_SHARE_TOKEN;
    }
    return fixture;
  }, [latencyMs, view]);
  // Click-based specs gate on this: a click before hydration is lost.
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => setHydrated(true), []);

  return (
    <div data-testid="dashboards-test-harness" data-hydrated={hydrated ? "1" : "0"} data-view={view}>
      <DashboardsApiProvider api={api} routes={routes} now={now}>
        {view === "detail" ? (
          <DashboardPage key={slug} idOrSlug={slug} />
        ) : view === "shared" ? (
          <DashboardSharedView token={token} />
        ) : (
          <DashboardGallery />
        )}
      </DashboardsApiProvider>
    </div>
  );
}
