"use client";

import dynamic from "next/dynamic";
import { useSearchParams } from "next/navigation";
import { Loader2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import ProjectsOverviewPage from "~/components/projects/projects-overview-page";

const SPA_NAVIGATE_EVENT = "spa:navigate";

const NotebookRuntimePage = dynamic(
  () => import("~/components/notebook/notebooks-page"),
  {
    ssr: false,
    loading: () => <NotebookRuntimeLoading />,
  },
);

function searchRequiresRuntime(params: URLSearchParams): boolean {
  return Boolean(
    params.get("project") ||
      params.get("file") ||
      params.get("session_id"),
  );
}

export default function ProjectsPage() {
  const searchParams = useSearchParams();
  const nextSearch = searchParams.toString();
  const [browserSearch, setBrowserSearch] = useState(() =>
    typeof window === "undefined" ? "" : window.location.search,
  );

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    setBrowserSearch(window.location.search);
  }, [nextSearch]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    const syncBrowserSearch = () => {
      setBrowserSearch(window.location.search);
    };

    window.addEventListener("popstate", syncBrowserSearch);
    window.addEventListener(SPA_NAVIGATE_EVENT, syncBrowserSearch);
    return () => {
      window.removeEventListener("popstate", syncBrowserSearch);
      window.removeEventListener(SPA_NAVIGATE_EVENT, syncBrowserSearch);
    };
  }, []);

  const effectiveSearchParams = useMemo(
    () => new URLSearchParams(browserSearch || nextSearch),
    [browserSearch, nextSearch],
  );

  if (searchRequiresRuntime(effectiveSearchParams)) {
    return <NotebookRuntimePage />;
  }

  return <ProjectsOverviewPage />;
}

function NotebookRuntimeLoading() {
  return (
    <div className="flex h-screen flex-col">
      <div className="flex items-center gap-3 border-b border-[var(--color-border)] bg-[var(--color-bg)] px-4 py-2">
        <Loader2 className="h-3.5 w-3.5 animate-spin text-[var(--color-text-dim)]" />
        <span className="text-[11px] uppercase tracking-wider text-[var(--color-text-dim)]">
          opening notebook runtime...
        </span>
      </div>
      <div className="flex flex-1 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-[var(--color-text-dim)]" />
      </div>
    </div>
  );
}
