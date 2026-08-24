"use client";

import Link from "next/link";
import { Sparkles } from "lucide-react";
import { useEffect, useState } from "react";

import { request } from "~/lib/api";
import { DashboardLoadingState } from "~/components/dashboard/dashboard-loading-state";

type DashboardListItem = {
  id: string;
  name: string;
  description: string | null;
  current_version_id: string;
  updated_at: string;
};

export default function DashboardsPage() {
  const [items, setItems] = useState<DashboardListItem[]>([]);
  const [error, setError] = useState<string>();
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    request<DashboardListItem[]>("/api/dashboards")
      .then(setItems)
      .catch((cause) => setError(String(cause)))
      .finally(() => setLoading(false));
  }, []);
  return (
    <main style={{ padding: 32, maxWidth: 1000, margin: "0 auto" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <div>
          <h1>Dashboards</h1>
          <p>Private, governed dashboards.</p>
        </div>
        <Link
          href="/dashboards/new"
          style={{ display: "inline-flex", alignItems: "center", gap: 7 }}
        >
          <Sparkles size={17} aria-hidden="true" />
          Create with AI
        </Link>
      </div>
      {error ? <p>{error}</p> : null}
      {loading ? (
        <DashboardLoadingState label="Loading dashboards…" page />
      ) : null}
      <div style={{ display: "grid", gap: 12, marginTop: 24 }}>
        {!loading &&
          items.map((item) => (
            <Link
              key={item.id}
              href={`/dashboards/${item.id}`}
              style={{
                border: "1px solid var(--color-border)",
                borderRadius: 10,
                padding: 16,
              }}
            >
              <strong>{item.name}</strong>
              <br />
              <span>{item.description}</span>
              <br />
              <small>
                Updated {new Date(item.updated_at).toLocaleString()}
              </small>
            </Link>
          ))}
        {!loading && !error && items.length === 0 ? (
          <p>No private dashboards yet.</p>
        ) : null}
      </div>
    </main>
  );
}
