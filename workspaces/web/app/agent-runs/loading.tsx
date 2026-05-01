import { PageHeaderSkeleton, TerminalBarSkeleton, Skeleton } from "@/components/ui/Skeleton";

export default function AgentRunsLoading() {
  return (
    <div className="p-8 max-w-[1400px]">
      <PageHeaderSkeleton />
      <TerminalBarSkeleton />
      <div className="flex flex-col gap-2">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-16 border border-[var(--color-border)]" />
        ))}
      </div>
    </div>
  );
}
