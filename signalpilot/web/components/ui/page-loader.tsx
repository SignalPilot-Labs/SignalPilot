"use client";

import { Loader2 } from "lucide-react";

/** Full-page centered loader shown while initial data loads. */
export function PageLoader({ label }: { label?: string }) {
  return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <div className="flex flex-col items-center gap-3">
        <Loader2 className="w-5 h-5 animate-spin text-[var(--color-text-dim)]" strokeWidth={1.5} />
        {label && (
          <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider uppercase">{label}</p>
        )}
      </div>
    </div>
  );
}

/** Skeleton bar for card loading states. */
export function SkeletonBar({ width = "100%", height = 12 }: { width?: string | number; height?: number }) {
  return (
    <div
      className="bg-[var(--color-bg-hover)] animate-pulse rounded-sm"
      style={{ width, height }}
    />
  );
}

/** Skeleton card matching the brutalist card style. */
export function SkeletonCard({ lines = 3 }: { lines?: number }) {
  return (
    <div className="border border-[var(--color-border)] p-5 space-y-3">
      <SkeletonBar width="40%" height={14} />
      {Array.from({ length: lines }).map((_, i) => (
        <SkeletonBar key={i} width={`${70 + Math.random() * 30}%`} height={10} />
      ))}
    </div>
  );
}

/** Grid of skeleton cards for pages that show card grids. */
export function SkeletonGrid({ count = 4, cols = 2 }: { count?: number; cols?: number }) {
  return (
    <div className={`grid gap-4 ${cols === 3 ? "grid-cols-3" : cols === 4 ? "grid-cols-4" : "grid-cols-2"}`}>
      {Array.from({ length: count }).map((_, i) => (
        <SkeletonCard key={i} />
      ))}
    </div>
  );
}

/** Skeleton for a stat row (label + value). */
export function SkeletonStat() {
  return (
    <div className="space-y-1.5">
      <SkeletonBar width="50%" height={10} />
      <SkeletonBar width="30%" height={18} />
    </div>
  );
}
