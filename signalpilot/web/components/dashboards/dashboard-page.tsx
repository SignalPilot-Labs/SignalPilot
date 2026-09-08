"use client";

// The /dashboards/[slug] page: header with actions, the live renderer,
// the settings drawer, and the version + refresh histories.

import { AlertTriangle } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";

import type { DashboardBundle, DashboardVersion, UpdateDashboardRequest } from "~/lib/api/dashboards";
import { saveBlobAs } from "~/lib/api/chat-files";
import { requestErrorStatus, userFacingErrorMessage } from "~/lib/api/client";
import { DashboardRenderer, type FilterState } from "~/dashboard-renderer";
import { ConfirmDialog } from "~/components/ui/confirm-dialog";
import { useToast } from "~/components/ui/toast";

import { DashboardHeader } from "./dashboard-header";
import { DashboardRefreshHistory } from "./dashboard-refresh-history";
import { DashboardSettingsDrawer } from "./dashboard-settings-drawer";
import { DashboardVersionList } from "./dashboard-version-list";
import { useDashboardsApi, useDashboardsClock, useDashboardsRoutes } from "./dashboards-api-context";
import { useDashboardDetail } from "./use-dashboard-detail";

/** Saves the spec as `<slug>.dashboard.json`. */
export function downloadSpecJson(bundle: DashboardBundle, slug: string) {
  saveBlobAs(
    new Blob([JSON.stringify(bundle.spec, null, 2)], { type: "application/json" }),
    `${slug}.dashboard.json`,
  );
}

function Placeholder({ text, tone = "dim" }: { text: string; tone?: "dim" | "error" }) {
  return (
    <div
      role={tone === "error" ? "alert" : undefined}
      className={`flex min-h-[320px] items-center justify-center gap-2 rounded-2xl border bg-[var(--color-bg-card)] px-6 text-center text-[12.5px] ${
        tone === "error"
          ? "border-[var(--color-error)]/30 text-[var(--color-error)]"
          : "border-[var(--color-border)] text-[var(--color-text-dim)]"
      }`}
    >
      {tone === "error" && <AlertTriangle className="h-4 w-4 flex-none" />}
      {text}
    </div>
  );
}

export function DashboardPage({ idOrSlug }: { idOrSlug: string }) {
  const api = useDashboardsApi();
  const routes = useDashboardsRoutes();
  const now = useDashboardsClock();
  const router = useRouter();
  const { toast } = useToast();
  const { state, reload, applyDashboard, prependRefresh, refreshing, pollError } = useDashboardDetail(idOrSlug);
  const [filterState, setFilterState] = useState<FilterState>({});
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [busy, setBusy] = useState(false);

  const run = useCallback(
    async (task: () => Promise<void>, failure: string) => {
      setBusy(true);
      try {
        await task();
      } catch (error) {
        toast(userFacingErrorMessage(error, failure) ?? failure, "error");
      } finally {
        setBusy(false);
      }
    },
    [toast],
  );

  if (state.phase === "loading") {
    return (
      <div className="min-h-screen p-5 md:p-8" aria-busy="true">
        <div className="mx-auto max-w-7xl space-y-4">
          <div className="h-6 w-48 animate-pulse rounded bg-[var(--color-bg-card)]" />
          <div className="h-[420px] animate-pulse rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-card)]" />
        </div>
      </div>
    );
  }
  if (state.phase === "error") {
    return (
      <div className="min-h-screen p-5 md:p-8">
        <div className="mx-auto max-w-7xl">
          <Link href={routes.gallery} className="text-[12px] text-[var(--color-text-muted)] hover:text-[var(--color-text)]">
            ← Dashboards
          </Link>
          <div className="mt-4">
            <Placeholder text={state.notFound ? "This dashboard does not exist or is not visible to you." : state.message} tone="error" />
          </div>
        </div>
      </div>
    );
  }

  const { detail, bundle, bundleError } = state;
  const { dashboard } = detail;

  const onRefreshNow = () =>
    run(async () => {
      try {
        const { refresh } = await api.refreshDashboardNow(dashboard.id);
        prependRefresh(refresh);
        toast("Refresh started.", "info");
      } catch (error) {
        if (requestErrorStatus(error) === 409) {
          toast("A refresh is already running.", "warning");
          await reload({ keepBundle: true });
          return;
        }
        throw error;
      }
    }, "Could not start the refresh.");

  const onSaveSettings = async (body: UpdateDashboardRequest) => {
    const { dashboard: updated } = await api.updateDashboard(dashboard.id, body);
    applyDashboard(updated);
    toast("Settings saved.", "success");
  };

  const onRestore = (version: DashboardVersion) =>
    run(async () => {
      await api.restoreDashboardVersion(dashboard.id, version.id);
      await reload();
      toast(`Restored version ${version.version_no}.`, "success");
    }, "Could not restore that version.");

  const onDownloadDataset = (version: DashboardVersion, name: string) =>
    run(async () => {
      const blob = await api.fetchDashboardDataset(dashboard.id, version.id, name);
      saveBlobAs(blob, version.dataset_meta[name]?.filename ?? name);
    }, `Could not download ${name}.`);

  const onEditInChat = () =>
    run(async () => {
      const { conversation_id } = await api.openDashboardEditChat(dashboard.id);
      router.push(routes.chat(conversation_id));
    }, "Could not open a chat for this dashboard.");

  const onShare = async () => {
    if (dashboard.visibility !== "link" || !dashboard.share_token) {
      toast("Set visibility to Link in Settings to get a share link.", "info");
      return;
    }
    const url = `${window.location.origin}${routes.shared(dashboard.share_token)}`;
    try {
      await navigator.clipboard.writeText(url);
      toast("Share link copied.", "success");
    } catch {
      toast(url, "info", 8000);
    }
  };

  const onArchiveToggle = () =>
    run(async () => {
      const result = dashboard.archived_at
        ? await api.unarchiveDashboard(dashboard.id)
        : await api.archiveDashboard(dashboard.id);
      applyDashboard(result.dashboard);
      toast(dashboard.archived_at ? "Dashboard restored to the gallery." : "Dashboard archived.", "success");
    }, "Could not change the archive state.");

  const onDelete = () =>
    run(async () => {
      setConfirmDelete(false);
      await api.deleteDashboard(dashboard.id);
      toast("Dashboard deleted.", "success");
      router.push(routes.gallery);
    }, "Could not delete the dashboard.");

  return (
    <div data-testid="dashboard-page" data-slug={dashboard.slug} className="min-h-screen p-5 md:p-8">
      <div className="mx-auto max-w-7xl">
        <DashboardHeader
          dashboard={dashboard}
          publishedAt={detail.versions.find((version) => version.id === dashboard.current_version_id)?.created_at ?? null}
          refreshing={refreshing}
          pollError={pollError}
          busy={busy}
          actions={{
            onRefreshNow: () => void onRefreshNow(),
            onOpenSettings: () => setSettingsOpen(true),
            onEditInChat: () => void onEditInChat(),
            onDownloadJson: () => {
              if (bundle) downloadSpecJson(bundle, dashboard.slug);
              else toast("The dashboard data has not loaded yet.", "warning");
            },
            onShare: () => void onShare(),
            onArchiveToggle: () => void onArchiveToggle(),
            onDelete: () => setConfirmDelete(true),
          }}
        />
        <div
          data-testid="dashboard-canvas"
          className="overflow-hidden rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-card)]"
        >
          {bundle ? (
            <DashboardRenderer
              spec={bundle.spec}
              datasets={bundle.datasets}
              theme="dark"
              filterState={filterState}
              onFilterStateChange={setFilterState}
            />
          ) : (
            <Placeholder
              text={bundleError ?? "This dashboard has no published version yet."}
              tone={bundleError ? "error" : "dim"}
            />
          )}
        </div>
        <div className="mt-6 grid gap-5 lg:grid-cols-2">
          <DashboardVersionList
            versions={detail.versions}
            currentVersionId={dashboard.current_version_id}
            canEdit={dashboard.can_edit}
            now={now}
            onRestore={onRestore}
            onDownloadDataset={onDownloadDataset}
          />
          <DashboardRefreshHistory refreshes={detail.refreshes} now={now} />
        </div>
      </div>
      <DashboardSettingsDrawer
        open={settingsOpen}
        dashboard={dashboard}
        onClose={() => setSettingsOpen(false)}
        onSubmit={onSaveSettings}
      />
      <ConfirmDialog
        open={confirmDelete}
        title="Delete this dashboard?"
        titleCase="sentence"
        message={`"${dashboard.name}" and every version of it will be removed for everyone. Chats that produced it are not affected.`}
        confirmLabel="Delete"
        cancelLabel="Keep"
        onConfirm={() => void onDelete()}
        onCancel={() => setConfirmDelete(false)}
      />
    </div>
  );
}
