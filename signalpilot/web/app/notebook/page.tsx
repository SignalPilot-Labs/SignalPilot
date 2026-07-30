"use client";

import dynamic from "next/dynamic";
import { Loader2 } from "lucide-react";

const NotebooksPage = dynamic(
  () => import("~/components/notebook/notebooks-page"),
  {
    ssr: false,
    loading: () => (
      <div className="flex min-h-screen items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-[var(--color-text-dim)]" />
      </div>
    ),
  },
);

// Full-page notebook IDE. Keep this route as a tiny shell so the initial
// /notebook request does not compile the notebook runtime graph in Docker.
export default function NotebookPage() {
  return <NotebooksPage />;
}
