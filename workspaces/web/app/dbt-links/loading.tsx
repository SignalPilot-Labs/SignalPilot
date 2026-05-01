import { Skeleton } from "@/components/ui/Skeleton";

export default function DbtLinksLoading() {
  return (
    <main className="p-6">
      <Skeleton className="h-8 w-48 mb-4" />
      <div className="rounded-card border border-border bg-surface p-6 shadow-card flex flex-col gap-2">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-14 rounded-card" />
        ))}
      </div>
    </main>
  );
}
