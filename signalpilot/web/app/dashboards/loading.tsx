import { Skeleton } from "@/components/ui/skeleton";

export default function DashboardsLoading() {
  return (
    <div className="p-8 max-w-[1400px]">
      <Skeleton className="h-8 w-48 mb-4" />
      <Skeleton className="h-10 w-full mb-6" />
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-32" />
        ))}
      </div>
    </div>
  );
}
