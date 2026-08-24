"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

import { DashboardRuntimeProvider } from "~/components/dashboard/dashboard-runtime-provider";
import { request } from "~/lib/api";
import type { DashboardDefinition } from "~/lib/dashboard/contracts";

type DashboardDetail = {
  dashboard: { id: string; current_version_id: string };
  version: { id: string; definition: DashboardDefinition };
};

export default function DashboardDetailPage() {
  const params = useParams<{ dashboardId: string }>();
  const [detail, setDetail] = useState<DashboardDetail>();
  const [error, setError] = useState<string>();
  useEffect(() => {
    const version = new URLSearchParams(window.location.search).get("version");
    request<DashboardDetail>(
      `/api/dashboards/${params.dashboardId}${version ? `?version_id=${encodeURIComponent(version)}` : ""}`,
    )
      .then(setDetail)
      .catch((cause) =>
        setError(
          cause instanceof Error ? cause.message : "Dashboard failed to load",
        ),
      );
  }, [params.dashboardId]);
  if (error) return <main style={{ padding: 32 }}>{error}</main>;
  if (!detail)
    return <main style={{ padding: 32 }}>Loading immutable dashboard…</main>;
  return (
    <DashboardRuntimeProvider
      dashboardId={detail.dashboard.id}
      versionId={detail.version.id}
      definition={detail.version.definition}
    />
  );
}
