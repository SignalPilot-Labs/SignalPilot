import { Skeleton } from "@/components/ui/Skeleton";

export default function ChartsNewLoading() {
  return (
    <main className="p-6">
      <Skeleton className="h-8 w-48 mb-6" />
      <div className="flex flex-col gap-4 max-w-2xl">
        <Skeleton className="h-10 rounded-control" />
        <Skeleton className="h-10 rounded-control" />
        <Skeleton className="h-40 rounded-control" />
        <Skeleton className="h-10 w-24 rounded-control" />
      </div>
    </main>
  );
}
