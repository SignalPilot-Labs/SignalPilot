"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

import { DashboardRuntimeProvider } from "~/components/dashboard/dashboard-runtime-provider";
import {
  DashboardAuthoringPanel,
  type DashboardAuthoringSession,
} from "~/components/dashboard/dashboard-authoring-panel";
import type { DashboardQueryReceipt } from "~/lib/dashboard/api-data-source";
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
  const [preview, setPreview] = useState<DashboardAuthoringSession>();
  const [receipts, setReceipts] = useState<
    Record<string, DashboardQueryReceipt>
  >({});
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
    <>
      <DashboardRuntimeProvider
        key={
          preview
            ? `${preview.id}:${preview.custom_sql_confirmed}`
            : detail.version.id
        }
        dashboardId={detail.dashboard.id}
        versionId={detail.version.id}
        definition={preview?.definition ?? detail.version.definition}
        authoringSessionId={preview?.id}
        onVisibleReceiptsChange={setReceipts}
      />
      <DashboardAuthoringPanel
        dashboardId={detail.dashboard.id}
        versionId={detail.version.id}
        preview={preview}
        visibleCompleteResultIds={Object.values(receipts)
          .filter((receipt) => receipt.completeness === "complete")
          .map((receipt) => receipt.dashboard_result_id)}
        onPreview={setPreview}
        onDiscard={() => setPreview(undefined)}
      />
    </>
  );
}
