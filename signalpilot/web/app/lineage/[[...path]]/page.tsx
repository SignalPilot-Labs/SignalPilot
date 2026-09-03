"use client";

/**
 * Lineage routes (optional catch-all):
 *   /lineage                 full dbt map
 *   /lineage/<model>         focus mode — bare model name or dbt unique_id
 *   /lineage/<model>/raw     focus mode with the Raw Tables panel
 *
 * `?project=<id>` overrides the remembered project. After the first render
 * the page keeps the URL in sync itself (history.replaceState), so this
 * route only seeds the initial view.
 */

import { Suspense, use } from "react";
import { useSearchParams } from "next/navigation";

import { DbtMapPage, type LineageRoute } from "~/components/lineage/dbt-map-page";

function parseRoute(path: string[] | undefined, projectId: string | null): LineageRoute {
  const segments = (path ?? []).map((s) => {
    try {
      return decodeURIComponent(s);
    } catch {
      return s;
    }
  });
  const raw = segments.length > 1 && segments[segments.length - 1].toLowerCase() === "raw";
  const ref = segments.length > 0 ? segments.slice(0, raw ? -1 : undefined).join("/") : null;
  return { ref: ref || null, raw, projectId };
}

function LineageRouteInner({ path }: { path: string[] | undefined }) {
  const searchParams = useSearchParams();
  const route = parseRoute(path, searchParams.get("project"));
  // Remount when the seed changes via client navigation (e.g. a chat link
  // clicked while already on /lineage) so the new deep link takes effect.
  const key = `${route.projectId ?? ""}:${route.ref ?? ""}:${route.raw}`;
  return <DbtMapPage key={key} route={route} />;
}

export default function LineagePage({
  params,
}: {
  params: Promise<{ path?: string[] }>;
}) {
  const { path } = use(params);
  return (
    <Suspense fallback={null}>
      <LineageRouteInner path={path} />
    </Suspense>
  );
}
