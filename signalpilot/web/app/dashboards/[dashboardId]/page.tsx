"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  Archive,
  ArrowLeft,
  BadgeCheck,
  Building2,
  Download,
  Ellipsis,
  GitFork,
  GitBranch,
  Lock,
} from "lucide-react";

import { DashboardRuntimeProvider } from "~/components/dashboard/dashboard-runtime-provider";
import { DashboardLoadingState } from "~/components/dashboard/dashboard-loading-state";
import { DashboardAuthoringPanel } from "~/components/dashboard/dashboard-authoring-panel";
import type { DashboardQueryReceipt } from "~/lib/dashboard/api-data-source";
import { request } from "~/lib/api";
import type { DashboardDefinition } from "~/lib/dashboard/contracts";
import type {
  DashboardDrillStep,
  DashboardRuntimeFilter,
} from "~/lib/dashboard/contracts";
import { captureDashboardHtmlExport } from "~/lib/dashboard/html-export";

import pageStyles from "../dashboards.module.css";

type DashboardDetail = {
  dashboard: {
    id: string;
    current_version_id: string;
    visibility: "private" | "organization";
    is_owner: boolean;
    parent_dashboard_id: string | null;
    parent_version_id: string | null;
  };
  version: { id: string; definition: DashboardDefinition };
};

type DashboardSuggestion = {
  dashboard_id: string;
  dashboard_name: string;
  chart_title: string;
  owner_user_id: string;
  confidence: "high";
  freshness_at: string | null;
};

export default function DashboardDetailPage() {
  const params = useParams<{ dashboardId: string }>();
  const router = useRouter();
  const [detail, setDetail] = useState<DashboardDetail>();
  const [error, setError] = useState<string>();
  const [receipts, setReceipts] = useState<
    Record<string, DashboardQueryReceipt>
  >({});
  const [filters, setFilters] = useState<DashboardRuntimeFilter[]>([]);
  const [drills, setDrills] = useState<Record<string, DashboardDrillStep[]>>(
    {},
  );
  const [suggestions, setSuggestions] = useState<DashboardSuggestion[]>([]);
  const [actionPending, setActionPending] = useState(false);
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
  useEffect(() => {
    request<DashboardSuggestion[]>(
      `/api/dashboards/${params.dashboardId}/suggestions`,
    )
      .then(setSuggestions)
      .catch(() => setSuggestions([]));
  }, [params.dashboardId]);
  if (error) return <main style={{ padding: 32 }}>{error}</main>;
  if (!detail)
    return (
      <main style={{ padding: 32 }}>
        <DashboardLoadingState label="Loading dashboard…" page />
      </main>
    );
  const exportReady = Object.keys(receipts).length > 0;
  return (
    <>
      <DashboardRuntimeProvider
        key={detail.version.id}
        dashboardId={detail.dashboard.id}
        versionId={detail.version.id}
        definition={detail.version.definition}
        onVisibleReceiptsChange={setReceipts}
        onRuntimeFiltersChange={setFilters}
        onRuntimeDrillsChange={setDrills}
        leadingAction={
          <Link
            href="/dashboards"
            className={pageStyles.leadingBackButton}
            aria-label="Back to dashboards"
            title="Back to dashboards"
          >
            <ArrowLeft size={17} aria-hidden="true" />
          </Link>
        }
        lifecycleActions={
          <nav
            className={pageStyles.iconActions}
            aria-label="Dashboard actions"
          >
            {detail.dashboard.is_owner ? (
              <DashboardAuthoringPanel
                dashboardId={detail.dashboard.id}
                versionId={detail.version.id}
                baseDefinition={detail.version.definition}
                onApplied={(applied) =>
                  window.location.assign(
                    `/dashboards/${applied.dashboard.id}?version=${applied.version.id}`,
                  )
                }
              />
            ) : null}
            <details className={pageStyles.actionMenu}>
              <summary
                className={pageStyles.iconButton}
                aria-label="More dashboard actions"
                title="More dashboard actions"
              >
                <Ellipsis size={18} aria-hidden="true" />
              </summary>
              <div className={pageStyles.actionMenuPanel}>
                {detail.dashboard.is_owner ? (
                  <div className={pageStyles.menuGroup}>
                    <span>Visibility</span>
                    {(["private", "organization"] as const).map(
                      (visibility) => (
                        <button
                          type="button"
                          key={visibility}
                          disabled={
                            actionPending ||
                            detail.dashboard.visibility === visibility
                          }
                          onClick={() => {
                            setActionPending(true);
                            void request<DashboardDetail>(
                              `/api/dashboards/${detail.dashboard.id}/visibility`,
                              {
                                method: "POST",
                                body: JSON.stringify({ visibility }),
                              },
                            )
                              .then(setDetail)
                              .catch((cause) => setError(String(cause)))
                              .finally(() => setActionPending(false));
                          }}
                        >
                          {visibility === "private" ? (
                            <Lock size={17} aria-hidden="true" />
                          ) : (
                            <Building2 size={17} aria-hidden="true" />
                          )}
                          <span>
                            {visibility === "private"
                              ? "Private"
                              : "Organization"}
                          </span>
                        </button>
                      ),
                    )}
                  </div>
                ) : null}
                <button
                  type="button"
                  disabled={actionPending}
                  onClick={() => {
                    setActionPending(true);
                    void request<DashboardDetail>(
                      `/api/dashboards/${detail.dashboard.id}/fork`,
                      {
                        method: "POST",
                        body: JSON.stringify({
                          version_id: detail.version.id,
                        }),
                      },
                    )
                      .then((forked) =>
                        router.push(`/dashboards/${forked.dashboard.id}`),
                      )
                      .catch((cause) => setError(String(cause)))
                      .finally(() => setActionPending(false));
                  }}
                >
                  <GitFork size={17} aria-hidden="true" />
                  <span>Fork this version</span>
                </button>
                <button
                  type="button"
                  disabled={actionPending || !exportReady}
                  onClick={() => {
                    if (
                      !window.confirm(
                        "The offline export contains the dashboard exactly as shown, including its visible governed data. Download it?",
                      )
                    )
                      return;
                    const root = document.querySelector<HTMLElement>(
                      "[data-dashboard-export-root]",
                    );
                    if (!root)
                      return setError("Dashboard export is unavailable");
                    setActionPending(true);
                    const resultIds = Object.values(receipts).map(
                      (receipt) => receipt.dashboard_result_id,
                    );
                    void request<{ warning: string }>(
                      `/api/dashboards/${detail.dashboard.id}/exports/html`,
                      {
                        method: "POST",
                        body: JSON.stringify({
                          version_id: detail.version.id,
                          dashboard_result_ids: resultIds,
                          dashboard_filters: filters,
                          drill_paths: Object.fromEntries(
                            Object.entries(drills).map(([chartId, path]) => [
                              chartId,
                              path.map((step) => ({
                                field_id: step.fieldId,
                                value: step.value,
                              })),
                            ]),
                          ),
                          acknowledge_sensitive_data: true,
                        }),
                      },
                    )
                      .then(() => {
                        const html = captureDashboardHtmlExport({
                          root,
                          title: detail.version.definition.name,
                          sourceUrl: window.location.href,
                        });
                        const url = URL.createObjectURL(
                          new Blob([html], {
                            type: "text/html;charset=utf-8",
                          }),
                        );
                        const anchor = document.createElement("a");
                        anchor.href = url;
                        anchor.download = `${detail.version.definition.name.replace(/[^a-z0-9]+/gi, "-").toLowerCase() || "dashboard"}.html`;
                        anchor.click();
                        window.setTimeout(() => URL.revokeObjectURL(url), 0);
                      })
                      .catch((cause) => setError(String(cause)))
                      .finally(() => setActionPending(false));
                  }}
                >
                  <Download size={17} aria-hidden="true" />
                  <span>Export dashboard</span>
                </button>
                {detail.dashboard.parent_dashboard_id &&
                detail.dashboard.parent_version_id ? (
                  <Link
                    href={`/dashboards/${detail.dashboard.parent_dashboard_id}?version=${detail.dashboard.parent_version_id}`}
                  >
                    <GitBranch size={17} aria-hidden="true" />
                    <span>Open source version</span>
                  </Link>
                ) : null}
                {detail.dashboard.is_owner ? (
                  <button
                    type="button"
                    disabled={actionPending}
                    onClick={() => {
                      if (
                        !window.confirm(
                          "Archive this dashboard? You can restore it from Mine.",
                        )
                      )
                        return;
                      setActionPending(true);
                      void request(
                        `/api/dashboards/${detail.dashboard.id}/archive`,
                        { method: "POST" },
                      )
                        .then(() => router.push("/dashboards?archived=1"))
                        .catch((cause) => setError(String(cause)))
                        .finally(() => setActionPending(false));
                    }}
                  >
                    <Archive size={17} aria-hidden="true" />
                    <span>Archive dashboard</span>
                  </button>
                ) : null}
              </div>
            </details>
          </nav>
        }
        lifecycleNotice={
          suggestions.length ? (
            <Link
              className={pageStyles.matchNotice}
              href={`/dashboards/${suggestions[0].dashboard_id}`}
            >
              <BadgeCheck size={15} aria-hidden="true" />
              <span>
                Exact semantic match in {suggestions[0].dashboard_name}
              </span>
            </Link>
          ) : null
        }
      />
    </>
  );
}
