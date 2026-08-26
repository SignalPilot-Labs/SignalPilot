"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { RefreshCw, Search, X } from "lucide-react";
import { useReports, invalidateReports } from "~/lib/hooks/use-gateway-data";
import { PageHeader } from "~/components/ui/page-header";
import { ReportList, ReportViewer } from "~/components/reports/report-view";
import "../knowledge/knowledge.css";

function ReportsPageInner() {
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
    <div className="kb-root h-screen flex flex-col p-8 overflow-hidden animate-fade-in">
      <PageHeader
        title="reports"
        subtitle="html"
        description="rendered HTML reports — shareable, sandboxed"
        actions={
          <button onClick={() => invalidateReports()} className="kb-btn kb-btn-ghost">
            <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`} strokeWidth={1.5} />
            Refresh
          </button>
        }
      />

      <div className="kb-split flex flex-1 min-h-0 mt-4">
        {/* List rail */}
        <div className="kb-sidebar w-72 flex-shrink-0 flex flex-col min-h-0">
          <div className="p-3 border-b border-[var(--kb-border)]">
            <div className="kb-search">
              <Search size={15} style={{ color: "var(--color-text-dim)", flex: "0 0 auto" }} />
              <input
                value={searchQ}
                onChange={(e) => setSearchQ(e.target.value)}
                placeholder="Search reports…"
              />
              {searchQ && (
                <button className="kb-search-clear" onClick={() => setSearchQ("")} aria-label="clear search">
                  <X size={13} />
                </button>
              )}
            </div>
          </div>
          <div className="flex-1 min-h-0 overflow-y-auto">
            <ReportList reports={reports} selectedId={selectedId} onSelect={selectReport} filterQ={searchQ} />
          </div>
        </div>

        {/* Viewer */}
        <div className="kb-reader">
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
