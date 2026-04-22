/**
 * Skeleton loading placeholders with shimmer effect.
 * Terminal-aesthetic loading states matching the design system.
 */

export function Skeleton({ className = "" }: { className?: string }) {
  return (
    <div className={`animate-shimmer ${className}`} />
  );
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
          <Skeleton className={`h-2.5 ${i === 0 ? "w-20" : i === columns - 1 ? "w-12" : "w-28"}`} />
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
    <div className="p-8 max-w-[1400px] animate-fade-in">
      <PageHeaderSkeleton />
      <TerminalBarSkeleton />

      {/* Metric cards */}
      <div className="grid grid-cols-4 gap-px mb-px bg-[var(--color-border)] border border-[var(--color-border)]">
        <CardSkeleton />
        <CardSkeleton />
        <CardSkeleton />
        <CardSkeleton />
      </div>
      <div className="grid grid-cols-4 gap-px mb-8 bg-[var(--color-border)]">
        <CardSkeleton />
        <CardSkeleton />
        <CardSkeleton />
        <CardSkeleton />
      </div>

      {/* Chart area */}
      <div className="grid grid-cols-3 gap-4 mb-8">
        <div className="col-span-2 border border-[var(--color-border)] bg-[var(--color-bg-card)] p-4">
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
 * API Keys page loading skeleton.
 * Matches the PageHeader + TerminalBar + section header + key rows layout.
 */
export function ApiKeysSkeleton() {
  return (
    <div className="p-8 max-w-3xl animate-fade-in">
      <PageHeaderSkeleton />
      <TerminalBarSkeleton />

      {/* Section header row with create button */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Skeleton className="w-3.5 h-3.5" />
          <Skeleton className="h-2.5 w-20" />
        </div>
        <Skeleton className="h-7 w-28" />
      </div>

      {/* Keys table */}
      <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] overflow-hidden">
        {/* Table header */}
        <div className="flex items-center gap-4 px-5 py-2 border-b border-[var(--color-border)] bg-[var(--color-bg)]">
          <Skeleton className="flex-1 h-2" />
          <Skeleton className="w-28 h-2 flex-shrink-0" />
          <Skeleton className="w-44 h-2 flex-shrink-0" />
          <Skeleton className="w-28 h-2 flex-shrink-0" />
          <Skeleton className="w-24 h-2 flex-shrink-0" />
          <Skeleton className="w-16 h-2 flex-shrink-0" />
        </div>
        {/* Key rows */}
        {Array.from({ length: 3 }, (_, i) => (
          <div key={i} className="flex items-center gap-4 px-5 py-3 border-b border-[var(--color-border)]">
            <Skeleton className="flex-1 h-2.5" />
            <Skeleton className="w-28 h-2.5 flex-shrink-0" />
            <div className="w-44 flex-shrink-0 flex gap-1.5">
              <Skeleton className="h-5 w-12" />
              <Skeleton className="h-5 w-12" />
            </div>
            <Skeleton className="w-28 h-2.5 flex-shrink-0" />
            <Skeleton className="w-24 h-2.5 flex-shrink-0" />
            <Skeleton className="w-16 h-6 flex-shrink-0" />
          </div>
        ))}
      </div>
    </div>
  );
}

/**
 * Billing page loading skeleton.
 * Matches the PageHeader + TerminalBar + current plan card + two upgrade plan cards layout.
 */
export function BillingSkeleton() {
  return (
    <div className="p-8 max-w-3xl animate-fade-in">
      <PageHeaderSkeleton />
      <TerminalBarSkeleton />

      {/* Current plan section header */}
      <div className="flex items-center gap-2 mb-4">
        <Skeleton className="w-3.5 h-3.5" />
        <Skeleton className="h-2.5 w-24" />
      </div>

      {/* Current plan card */}
      <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-5 mb-8">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Skeleton className="h-5 w-12" />
            <div className="space-y-1.5">
              <Skeleton className="h-2.5 w-32" />
              <Skeleton className="h-2 w-24" />
            </div>
          </div>
          <Skeleton className="h-8 w-36" />
        </div>
      </div>

      {/* Upgrade section header */}
      <div className="flex items-center gap-2 mb-4">
        <Skeleton className="w-3.5 h-3.5" />
        <Skeleton className="h-2.5 w-24" />
      </div>

      {/* Two upgrade plan cards side by side */}
      <div className="flex gap-4">
        {Array.from({ length: 2 }, (_, i) => (
          <div key={i} className="flex-1 border border-[var(--color-border)] bg-[var(--color-bg-card)] p-5">
            {/* Plan header */}
            <div className="flex items-start justify-between mb-3">
              <div className="flex items-center gap-2">
                <Skeleton className="w-3.5 h-3.5" />
                <Skeleton className="h-2.5 w-16" />
              </div>
              <Skeleton className="h-5 w-12" />
            </div>
            {/* Description */}
            <Skeleton className="h-2 w-full mb-1" />
            <Skeleton className="h-2 w-3/4 mb-4" />
            {/* Feature list */}
            <div className="space-y-2 mb-5">
              {Array.from({ length: 4 }, (_, j) => (
                <div key={j} className="flex items-center gap-2">
                  <Skeleton className="w-3 h-3 flex-shrink-0" />
                  <Skeleton className="h-2 w-32" />
                </div>
              ))}
            </div>
            {/* Upgrade button */}
            <Skeleton className="h-8 w-full" />
          </div>
        ))}
      </div>
    </div>
  );
}

/**
 * Connection list skeleton.
 */
export function ConnectionsSkeleton() {
  return (
    <div className="p-8 animate-fade-in">
      <PageHeaderSkeleton />
      <TerminalBarSkeleton />
      <div className="space-y-2">
        {Array.from({ length: 3 }, (_, i) => (
          <div key={i} className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-4">
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
