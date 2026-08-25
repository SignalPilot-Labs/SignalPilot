"use client";

import Link from "next/link";
import {
  BadgeAlert,
  BadgeCheck,
  Building2,
  Lock,
  RotateCcw,
  Search,
  Sparkles,
  UserRound,
} from "lucide-react";
import { useEffect, useState } from "react";

import { request } from "~/lib/api";
import { DashboardLoadingState } from "~/components/dashboard/dashboard-loading-state";

import styles from "./dashboards.module.css";

type DashboardListItem = {
  id: string;
  name: string;
  description: string | null;
  current_version_id: string;
  updated_at: string;
  visibility: "private" | "organization";
  owner_user_id: string;
  is_owner: boolean;
  archived_at: string | null;
  high_confidence_charts: number;
  low_confidence_charts: number;
};

export default function DashboardsPage() {
  const [items, setItems] = useState<DashboardListItem[]>([]);
  const [error, setError] = useState<string>();
  const [loading, setLoading] = useState(true);
  const [scope, setScope] = useState<"mine" | "organization">("mine");
  const [search, setSearch] = useState("");
  const [includeArchived, setIncludeArchived] = useState(false);
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("archived") === "1")
      setIncludeArchived(true);
  }, []);
  useEffect(() => {
    setLoading(true);
    const query = new URLSearchParams({ scope });
    if (search.trim()) query.set("search", search.trim());
    if (includeArchived && scope === "mine")
      query.set("include_archived", "true");
    request<DashboardListItem[]>(`/api/dashboards?${query}`)
      .then(setItems)
      .catch((cause) => setError(String(cause)))
      .finally(() => setLoading(false));
  }, [includeArchived, scope, search]);
  return (
    <main className={styles.indexPage}>
      <header className={styles.indexHeader}>
        <div>
          <h1>Dashboards</h1>
          <p>Governed dashboards for you and your organization.</p>
        </div>
        <Link
          href="/dashboards/new"
          className={styles.primaryIconButton}
          aria-label="Create dashboard with AI"
          title="Create dashboard with AI"
        >
          <Sparkles size={17} aria-hidden="true" />
        </Link>
      </header>
      {error ? <p className={styles.error}>{error}</p> : null}
      <div className={styles.indexControls}>
        <div
          className={styles.tabs}
          role="tablist"
          aria-label="Dashboard scope"
        >
          <button
            type="button"
            role="tab"
            aria-selected={scope === "mine"}
            onClick={() => setScope("mine")}
          >
            <UserRound size={15} aria-hidden="true" />
            Mine
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={scope === "organization"}
            onClick={() => setScope("organization")}
          >
            <Building2 size={15} aria-hidden="true" />
            Organization
          </button>
        </div>
        <label className={styles.searchBox}>
          <Search size={15} aria-hidden="true" />
          <input
            aria-label="Search dashboards"
            type="search"
            placeholder="Search dashboards"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
        {scope === "mine" ? (
          <label className={styles.archiveToggle}>
            <input
              type="checkbox"
              checked={includeArchived}
              onChange={(event) => setIncludeArchived(event.target.checked)}
            />
            Archived
          </label>
        ) : null}
      </div>
      {loading ? (
        <DashboardLoadingState label="Loading dashboards…" page />
      ) : null}
      <div className={styles.cardGrid}>
        {!loading &&
          items.map((item) => (
            <article
              key={item.id}
              className={`${styles.dashboardCard} ${item.archived_at ? styles.archivedCard : ""}`}
            >
              <Link href={`/dashboards/${item.id}`} className={styles.cardLink}>
                <div className={styles.cardTitleRow}>
                  <strong>{item.name}</strong>
                  {item.visibility === "organization" ? (
                    <Building2 size={15} aria-label="Organization dashboard" />
                  ) : (
                    <Lock size={15} aria-label="Private dashboard" />
                  )}
                </div>
                <p>{item.description || "No description"}</p>
                <div className={styles.cardMeta}>
                  <span title="High-confidence semantic charts">
                    <BadgeCheck size={14} aria-hidden="true" />
                    {item.high_confidence_charts}
                  </span>
                  {item.low_confidence_charts ? (
                    <span title="Low-confidence custom SQL charts">
                      <BadgeAlert size={14} aria-hidden="true" />
                      {item.low_confidence_charts}
                    </span>
                  ) : null}
                  <time dateTime={item.updated_at}>
                    {new Date(item.updated_at).toLocaleDateString()}
                  </time>
                </div>
              </Link>
              {item.archived_at ? (
                <button
                  type="button"
                  className={styles.cardIconButton}
                  aria-label={`Restore ${item.name}`}
                  title="Restore dashboard"
                  onClick={() => {
                    void request(`/api/dashboards/${item.id}/restore`, {
                      method: "POST",
                    }).then(() =>
                      setItems((current) =>
                        current.map((candidate) =>
                          candidate.id === item.id
                            ? { ...candidate, archived_at: null }
                            : candidate,
                        ),
                      ),
                    );
                  }}
                >
                  <RotateCcw size={15} aria-hidden="true" />
                </button>
              ) : null}
            </article>
          ))}
        {!loading && !error && items.length === 0 ? (
          <p>No dashboards match this view.</p>
        ) : null}
      </div>
    </main>
  );
}
