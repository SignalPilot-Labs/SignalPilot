"use client";

import { useEffect, useState } from "react";

/**
 * Live-updating relative timestamp — terminal-aesthetic.
 * Shows "3s", "2m", "1h", etc. with optional auto-update.
 *
 * Accepts epoch seconds (number) or ISO strings. When a string is provided,
 * it is parsed via Date.parse (milliseconds) and divided by 1000.
 * If the result is NaN, the original string is rendered verbatim — no silent fallback.
 */
function toEpochSeconds(timestamp: number | string): number | null {
  if (typeof timestamp === "number") {
    return timestamp;
  }
  const ms = Date.parse(timestamp);
  if (Number.isNaN(ms)) {
    return null;
  }
  return ms / 1000;
}

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
  live = true,
  className = "",
}: {
  timestamp: number | string;
  live?: boolean;
  className?: string;
}) {
  const epochSeconds = toEpochSeconds(timestamp);

  const [display, setDisplay] = useState(() =>
    epochSeconds !== null ? formatRelative(epochSeconds) : String(timestamp)
  );

  useEffect(() => {
    if (epochSeconds === null || !live) return;
    const interval = setInterval(() => {
      setDisplay(formatRelative(epochSeconds));
    }, 5000);
    return () => clearInterval(interval);
  }, [epochSeconds, live]);

  // Bad input: surface literal value in a <time> tag with no dateTime
  if (epochSeconds === null) {
    return (
      <time className={`tabular-nums ${className}`}>
        {String(timestamp)}
      </time>
    );
  }

  const isoString = new Date(epochSeconds * 1000).toISOString();
  const absoluteString = new Date(epochSeconds * 1000).toLocaleString();

  return (
    <time
      dateTime={isoString}
      title={absoluteString}
      className={`tabular-nums ${className}`}
    >
      {display}
    </time>
  );
}
