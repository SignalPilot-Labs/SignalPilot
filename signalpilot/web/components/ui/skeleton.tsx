/**
 * Skeleton loading placeholders with shimmer effect.
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
        <Skeleton className="w-8 h-8" />
        <Skeleton className="h-3 w-24" />
      </div>
      <Skeleton className="h-6 w-16 mb-1" />
      <Skeleton className="h-2 w-20" />
    </div>
  );
}

export function TableRowSkeleton({ columns = 5 }: { columns?: number }) {
  return (
    <tr>
      {Array.from({ length: columns }).map((_, i) => (
        <td key={i} className="px-4 py-3">
          <Skeleton className={`h-3 ${i === 0 ? "w-24" : i === columns - 1 ? "w-12" : "w-32"}`} />
        </td>
      ))}
    </tr>
  );
}

export function PageHeaderSkeleton() {
  return (
    <div className="mb-8">
      <Skeleton className="h-6 w-48 mb-2" />
      <Skeleton className="h-3 w-72" />
    </div>
  );
}
