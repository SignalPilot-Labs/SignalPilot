"use client";

/**
 * Lineage routes (optional catch-all):
 *   /lineage                 full dbt map
 *   /lineage/<model>         focus mode: bare model name or dbt unique_id
 *   /lineage/<model>/raw     focus mode with the Raw Tables panel
 *
 * `?project=<id>` overrides the remembered project. The route is read from
 * the live pathname (not the server params) so both client navigations and
 * the page's own history.replaceState land in the same place. DbtMapPage
 * stays mounted across model changes and reacts to the route as props; the
 * cached project graph is never refetched for a model-to-model hop.
 */

import { Suspense } from "react";
import { usePathname, useSearchParams } from "next/navigation";

import { DbtMapPage } from "~/components/lineage/dbt-map-page";
import { parseLineagePath } from "~/components/lineage/lineage-nav";

function LineageRouteInner() {
  const pathname = usePathname() ?? "/lineage";
  const searchParams = useSearchParams();
  const route = parseLineagePath(pathname, searchParams.get("project"));
  return <DbtMapPage route={route} />;
}

export default function LineagePage() {
  return (
    <Suspense fallback={null}>
      <LineageRouteInner />
    </Suspense>
  );
}
