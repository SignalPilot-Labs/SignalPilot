"use client";

import { clsx } from "clsx";
import type { RunStatus } from "@/lib/types";
import { STATUS_META } from "@/lib/types";

export function StatusBadge({
  status,
  size = "sm",
}: {
  status: RunStatus;
  size?: "sm" | "md";
}) {
  const meta = STATUS_META[status] || STATUS_META.error;
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-full font-medium",
        meta.bg,
        meta.color,
        size === "sm" ? "px-2 py-0.5 text-[10px]" : "px-3 py-1 text-xs"
      )}
    >
      {meta.pulse && (
        <span className="relative flex h-1.5 w-1.5">
          <span
            className={clsx(
              "absolute inline-flex h-full w-full animate-ping rounded-full opacity-75",
              status === "running" ? "bg-emerald-400" : "bg-yellow-400"
            )}
          />
          <span
            className={clsx(
              "relative inline-flex h-1.5 w-1.5 rounded-full",
              status === "running" ? "bg-emerald-400" : "bg-yellow-400"
            )}
          />
        </span>
      )}
      {meta.label}
    </span>
  );
}
