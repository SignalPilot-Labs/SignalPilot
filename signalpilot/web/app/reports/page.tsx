"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { RefreshCw } from "lucide-react";
import { useReports, invalidateReports } from "~/lib/hooks/use-gateway-data";
import { PageHeader } from "~/components/ui/page-header";
import { ReportList, ReportViewer } from "~/components/reports/report-view";

const TABS = ["active", "pending", "archived", "reports"] as const;

function ReportsPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  // Selection is local state; the address bar is updated via history.replaceState
  // (no Next navigation) so deep-links work without re-render/Suspense churn.
  const [selectedId, setSelectedId] = useState<string | null>(() => searchParams.get("report"));
  const [searchQ, setSearchQ] = useState("");

  const { data: reports, isLoading } = useReports();

  function selectReport(id: string | null) {
    setSelectedId(id);
    if (typeof window !== "undefined") {
      window.history.replaceState(null, "", `/reports${id ? `?report=${id}` : ""}`);
    }
  }

  return (
    <div className="h-screen flex flex-col p-6 overflow-hidden">
      <PageHeader
        title="reports"
        subtitle="html"
        description="rendered HTML reports — shareable, sandboxed"
        actions={
          <button
            onClick={() => invalidateReports()}
            className="flex items-center gap-2 px-3 py-1.5 text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`} strokeWidth={1.5} />
            refresh
          </button>
        }
      />

      <div className="flex flex-1 min-h-0 border border-[var(--color-border)] bg-[var(--color-bg-card)] mt-4">
        {/* List rail */}
        <div className="w-72 flex-shrink-0 border-r border-[var(--color-border)] flex flex-col min-h-0">
          <div className="p-2 border-b border-[var(--color-border)] space-y-2">
            <input
              type="text"
              placeholder="filter reports..."
              value={searchQ}
              onChange={(e) => setSearchQ(e.target.value)}
              className="w-full px-2 py-1.5 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-[12px] focus:outline-none focus:border-[var(--color-text-dim)] tracking-wide"
            />
            <div className="flex items-center gap-1">
              {TABS.map((t) => (
                <button
                  key={t}
                  onClick={() =>
                    t === "reports" ? undefined : router.push(`/knowledge?status=${t}`)
                  }
                  className={`flex-1 py-1 text-[10px] uppercase tracking-[0.1em] transition-colors border ${
                    t === "reports"
                      ? "border-[var(--color-text-dim)] text-[var(--color-text)]"
                      : "border-[var(--color-border)] text-[var(--color-text-dim)] hover:text-[var(--color-text-muted)]"
                  }`}
                >
                  {t}
                </button>
              ))}
            </div>
          </div>
          <div className="flex-1 min-h-0 overflow-y-auto">
            <ReportList reports={reports} selectedId={selectedId} onSelect={selectReport} filterQ={searchQ} />
          </div>
        </div>

        {/* Viewer */}
        <div className="flex-1 flex flex-col min-w-0 min-h-0">
          <ReportViewer reportId={selectedId} onDeleted={() => selectReport(null)} />
        </div>
      </div>
    </div>
  );
}

export default function ReportsPage() {
  return (
    <Suspense fallback={null}>
      <ReportsPageInner />
    </Suspense>
  );
}
