"use client";

import { useEffect, useState } from "react";

/**
 * Live-updating relative timestamp — terminal-aesthetic.
 * Shows "3s", "2m", "1h", etc. with optional auto-update.
 */
function formatRelative(ts: number): string {
  const now = Date.now() / 1000;
  const diff = now - ts;

  if (diff < 0) return "future";
  if (diff < 60) return `${Math.floor(diff)}s`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
  if (diff < 604800) return `${Math.floor(diff / 86400)}d`;
  return `${Math.floor(diff / 604800)}w`;
}

export function TimeAgo({
  timestamp,
  live = false,
  className = "",
}: {
  timestamp: number;
  live?: boolean;
  className?: string;
}) {
  const [display, setDisplay] = useState(() => formatRelative(timestamp));

  useEffect(() => {
    if (!live) return;
    const interval = setInterval(() => {
      setDisplay(formatRelative(timestamp));
    }, 5000);
    return () => clearInterval(interval);
  }, [timestamp, live]);

  return (
    <time
      dateTime={new Date(timestamp * 1000).toISOString()}
      title={new Date(timestamp * 1000).toLocaleString()}
      className={`tabular-nums ${className}`}
    >
      {display}
    </time>
  );
}
