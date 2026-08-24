"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { request } from "~/lib/api";

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
  useEffect(() => {
    request<DashboardListItem[]>("/api/dashboards")
      .then(setItems)
      .catch((cause) => setError(String(cause)));
  }, []);
  return (
    <main style={{ padding: 32, maxWidth: 1000, margin: "0 auto" }}>
      <h1>Dashboards</h1>
      <p>Private, governed, immutable dashboard versions.</p>
      {error ? <p>{error}</p> : null}
      <div style={{ display: "grid", gap: 12, marginTop: 24 }}>
        {items.map((item) => (
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
              Version {item.current_version_id} ·{" "}
              {new Date(item.updated_at).toLocaleString()}
            </small>
          </Link>
        ))}
        {!error && items.length === 0 ? (
          <p>No private dashboards yet.</p>
        ) : null}
      </div>
    </main>
  );
}
