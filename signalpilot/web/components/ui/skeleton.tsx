/**
 * Skeleton loading placeholders with shimmer effect.
 * Terminal-aesthetic loading states matching the design system.
 */

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-shimmer ${className}`} />;
}

export function CardSkeleton() {
  return (
    <div className="bg-[var(--color-bg-card)] border border-[var(--color-border)] p-5">
      <div className="flex items-center gap-3 mb-3">
        <Skeleton className="w-3.5 h-3.5" />
        <Skeleton className="h-2 w-20" />
      </div>
      <Skeleton className="h-5 w-16 mb-2" />
      <Skeleton className="h-2 w-24" />
    </div>
  );
}

export function TableRowSkeleton({ columns = 5 }: { columns?: number }) {
  return (
    <tr className="border-b border-[var(--color-border)]/30">
      {Array.from({ length: columns }).map((_, i) => (
        <td key={i} className="px-4 py-3">
          <Skeleton
            className={`h-2.5 ${i === 0 ? "w-20" : i === columns - 1 ? "w-12" : "w-28"}`}
          />
        </td>
      ))}
    </tr>
  );
}

export function PageHeaderSkeleton() {
  return (
    <div className="mb-8">
      <div className="flex items-center gap-3 mb-2">
        <Skeleton className="h-5 w-32" />
        <Skeleton className="h-4 w-16" />
      </div>
      <Skeleton className="h-2 w-64" />
    </div>
  );
}

/**
 * Terminal bar skeleton matching the TerminalBar component.
 */
export function TerminalBarSkeleton() {
  return (
    <div className="flex items-center gap-3 mb-6 px-4 py-2.5 border border-[var(--color-border)] bg-[var(--color-bg-card)]">
      <Skeleton className="w-2 h-2" />
      <Skeleton className="h-2.5 w-48" />
      <div className="flex-1" />
      <Skeleton className="h-2.5 w-20" />
    </div>
  );
}

/**
 * Full dashboard loading skeleton.
 */
export function DashboardSkeleton() {
  return (
    <div className="p-4 sm:p-8 max-w-[1400px] animate-fade-in">
      <PageHeaderSkeleton />
      <TerminalBarSkeleton />

      {/* Metric cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-px mb-px bg-[var(--color-border)] border border-[var(--color-border)]">
        <CardSkeleton />
        <CardSkeleton />
        <CardSkeleton />
        <CardSkeleton />
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-px mb-8 bg-[var(--color-border)]">
        <CardSkeleton />
        <CardSkeleton />
        <CardSkeleton />
        <CardSkeleton />
      </div>

      {/* Chart area */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-8">
        <div className="sm:col-span-2 border border-[var(--color-border)] bg-[var(--color-bg-card)] p-4">
          <div className="flex items-center gap-2 mb-3">
            <Skeleton className="w-3 h-3" />
            <Skeleton className="h-2 w-24" />
          </div>
          <Skeleton className="h-20 w-full" />
        </div>
        <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-4">
          <div className="flex items-center gap-2 mb-3">
            <Skeleton className="w-3 h-3" />
            <Skeleton className="h-2 w-24" />
          </div>
          <Skeleton className="h-20 w-full" />
        </div>
      </div>

      {/* Activity list */}
      <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)]">
        <div className="px-4 py-3 border-b border-[var(--color-border)]">
          <Skeleton className="h-2.5 w-32" />
        </div>
        <div className="divide-y divide-[var(--color-border)]">
          {Array.from({ length: 6 }, (_, i) => (
            <div key={i} className="flex items-center gap-3 px-4 py-2.5">
              <Skeleton className="w-8 h-2.5" />
              <Skeleton className="h-2.5 flex-1" />
              <Skeleton className="w-10 h-2.5" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/**
 * Connection list skeleton.
 */
export function ConnectionsSkeleton() {
  return (
    <div className="p-4 sm:p-8 animate-fade-in">
      <PageHeaderSkeleton />
      <TerminalBarSkeleton />
      <div className="space-y-2">
        {Array.from({ length: 3 }, (_, i) => (
          <div
            key={i}
            className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-4"
          >
            <div className="flex items-center gap-4">
              <Skeleton className="w-3 h-3" />
              <div className="flex-1 space-y-1.5">
                <Skeleton className="h-3 w-32" />
                <Skeleton className="h-2 w-48" />
              </div>
              <Skeleton className="h-2.5 w-12" />
              <Skeleton className="h-6 w-16" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
