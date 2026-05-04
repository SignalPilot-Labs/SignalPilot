import { Skeleton } from "@/components/ui/Skeleton";

export default function ChartsLoading() {
  return (
    <div className="p-6">
      <Skeleton className="h-8 w-48 mb-4" />
      <div className="bg-[var(--color-bg-card)] border border-[var(--color-border)] p-6 flex flex-col gap-2">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-14" />
        ))}
      </div>
    </div>
  );
}
