import { Skeleton } from "@/components/ui/Skeleton";

export default function DashboardsLoading() {
  return (
    <div className="p-6">
      <Skeleton className="h-8 w-48 mb-4" />
      <div className="flex flex-col gap-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-14" />
        ))}
      </div>
    </div>
  );
}
