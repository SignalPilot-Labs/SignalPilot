import { clsx } from "clsx";

interface SkeletonProps {
  className?: string;
}

export function Skeleton({ className }: SkeletonProps) {
  return (
    <div
      className={clsx("animate-pulse bg-muted/30 rounded", className)}
      aria-hidden="true"
    />
  );
}
