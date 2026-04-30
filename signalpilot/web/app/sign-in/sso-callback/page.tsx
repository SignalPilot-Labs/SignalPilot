"use client";

import dynamic from "next/dynamic";
import { Loader2 } from "lucide-react";

const SSOCallbackClient = dynamic(
  () => import("./client"),
  {
    ssr: false,
    loading: () => (
      <div className="flex flex-col items-center justify-center min-h-screen gap-3 bg-[var(--color-bg)]">
        <Loader2 className="w-5 h-5 animate-spin text-[var(--color-text-dim)]" />
        <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider">
          verifying authentication...
        </p>
      </div>
    ),
  }
);

export default function SSOCallbackPage() {
  return <SSOCallbackClient />;
}
