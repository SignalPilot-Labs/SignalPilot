/**
 * Skeleton loading placeholders with shimmer effect.
 * Terminal-aesthetic loading states matching the design system.
 */

export function Skeleton({ className = "" }: { className?: string }) {
  return (
    <div className={`animate-shimmer ${className}`} aria-hidden="true" />
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
