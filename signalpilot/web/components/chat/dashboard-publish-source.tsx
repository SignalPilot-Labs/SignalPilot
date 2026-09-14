"use client";

// Where a chat dashboard file came from, and the strip that says so. The
// loader reads the gallery once and resolves the file's source: published
// from this conversation file ("Published as"), or pulled in by
// `dashboard_load_published` under `artifacts/<slug>.dashboard.json`
// ("Loaded from"). Either one is the default target of the next publish.

import { CheckCircle2, ExternalLink, FolderInput } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import type { PublishedDashboard } from "~/lib/api/dashboards";
import { realDashboardsRoutes } from "~/lib/dashboards/api";
import {
  resolveDashboardSource,
  type DashboardPublishApi,
  type DashboardSource,
} from "~/components/chat/dashboard-publish-form";

export type DashboardSourceState = {
  /** Every dashboard the caller can see; the dialog picks editable targets. */
  dashboards: PublishedDashboard[];
  /** The dashboard this file is a version of, when there is one. */
  source: DashboardSource | null;
  loaded: boolean;
  reload: () => Promise<void>;
  /** Record a publish result without a round trip. */
  setPublished: (dashboard: PublishedDashboard) => void;
};

/**
 * Loads the gallery on mount and resolves the file's source. A failed list
 * is silent: the user can still publish, and the dialog reports its own
 * failures.
 */
export function useDashboardSource(
  api: DashboardPublishApi,
  conversationId: string,
  file: { id: string; filename: string },
): DashboardSourceState {
  const { id: fileId, filename } = file;
  const [dashboards, setDashboards] = useState<PublishedDashboard[]>([]);
  const [source, setSource] = useState<DashboardSource | null>(null);
  const [loaded, setLoaded] = useState(false);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const reload = useCallback(async () => {
    try {
      const result = await api.listDashboards();
      if (!alive.current) return;
      setDashboards(result.dashboards);
      setSource(resolveDashboardSource(result.dashboards, conversationId, { id: fileId, filename }));
    } catch {
      // Gallery unavailable: nothing to show yet.
    } finally {
      if (alive.current) setLoaded(true);
    }
  }, [api, conversationId, fileId, filename]);
  useEffect(() => {
    if (!conversationId) {
      setLoaded(true);
      return;
    }
    void reload();
  }, [reload, conversationId]);
  const setPublished = useCallback((dashboard: PublishedDashboard) => {
    setSource({ dashboard, origin: "published" });
    setDashboards((list) => [dashboard, ...list.filter((item) => item.id !== dashboard.id)]);
  }, []);
  return { dashboards, source, loaded, reload, setPublished };
}

/** The inline "Published as <name>" / "Loaded from <name>" band under the
 * file header, with a link to the dashboard and the versioning action. */
export function DashboardSourceStrip({
  source,
  onPublishNewVersion,
}: {
  source: DashboardSource;
  onPublishNewVersion: () => void;
}) {
  const { dashboard, origin } = source;
  const published = origin === "published";
  const testId = published ? "chat-dashboard-published" : "chat-dashboard-loaded";
  return (
    <div
      data-testid={testId}
      data-origin={origin}
      data-dashboard-slug={dashboard.slug}
      className={`flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-[var(--color-border)] px-3 py-1.5 text-[11.5px] ${
        published ? "bg-[var(--color-success)]/[0.04]" : "bg-[var(--color-bg-hover)]/60"
      }`}
    >
      <span className="inline-flex items-center gap-1.5 text-[var(--color-text-muted)]">
        {published ? (
          <CheckCircle2 className="h-3.5 w-3.5 text-[var(--color-success)]" />
        ) : (
          <FolderInput className="h-3.5 w-3.5 text-[var(--color-text-dim)]" />
        )}
        {published ? "Published as" : "Loaded from"}{" "}
        <span className="font-medium text-[var(--color-text)]">{dashboard.name}</span>
        {dashboard.current_version_no != null && (
          <span className="text-[var(--color-text-dim)]">
            {published ? `v${dashboard.current_version_no}` : `(v${dashboard.current_version_no})`}
          </span>
        )}
      </span>
      <Link
        href={realDashboardsRoutes.dashboard(dashboard.slug)}
        data-testid={`${testId}-open`}
        className="inline-flex items-center gap-1 text-[var(--color-text)] underline decoration-[var(--color-border-active)] underline-offset-2 hover:decoration-[var(--color-text)]"
      >
        Open
        <ExternalLink className="h-3 w-3" />
      </Link>
      <button
        type="button"
        data-testid="chat-dashboard-publish-version"
        onClick={onPublishNewVersion}
        className="ml-auto rounded-md border border-[var(--color-border)] bg-[var(--color-bg-card)] px-2 py-0.5 text-[11px] text-[var(--color-text-muted)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
      >
        Publish new version
      </button>
    </div>
  );
}
