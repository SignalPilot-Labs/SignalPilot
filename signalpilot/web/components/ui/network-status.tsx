"use client";

import { useEffect, useState, useRef } from "react";

/**
 * Shows a slim banner when the gateway is unreachable.
 * Only visible on mobile — desktop users see the sidebar status indicators.
 * Polls /api/health every 15s when online, 5s when offline.
 */
export function NetworkStatus() {
  const [offline, setOffline] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => {
    let mounted = true;
    const url =
      typeof window !== "undefined"
        ? localStorage.getItem("sp_gateway_url") || "http://localhost:3300"
        : "";

    async function check() {
      try {
        const res = await fetch(`${url}/api/health`, {
          method: "GET",
          signal: AbortSignal.timeout(5000),
        });
        if (mounted) {
          setOffline(!res.ok);
          if (res.ok) setDismissed(false);
        }
      } catch {
        if (mounted) setOffline(true);
      }
      if (mounted) {
        // Check more frequently when offline
        timerRef.current = setTimeout(check, offline ? 5000 : 15000);
      }
    }

    // Also listen for browser online/offline events
    function handleOnline() {
      if (mounted) check();
    }
    function handleOffline() {
      if (mounted) setOffline(true);
    }

    check();
    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);

    return () => {
      mounted = false;
      clearTimeout(timerRef.current);
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, [offline]);

  if (!offline || dismissed) return null;

  return (
    <div className="sm:hidden fixed top-[calc(3rem+env(safe-area-inset-top,0px))] left-0 right-0 z-[45] animate-fade-in">
      <div className="flex items-center justify-between px-4 py-2 bg-[var(--color-error)]/10 border-b border-[var(--color-error)]/20">
        <div className="flex items-center gap-2">
          <svg
            width="12"
            height="12"
            viewBox="0 0 12 12"
            fill="none"
            className="flex-shrink-0"
          >
            <path
              d="M1 9L6 3L11 9"
              stroke="var(--color-error)"
              strokeWidth="1"
              fill="none"
            />
            <line
              x1="6"
              y1="5.5"
              x2="6"
              y2="7"
              stroke="var(--color-error)"
              strokeWidth="1"
              strokeLinecap="round"
            />
            <circle cx="6" cy="8" r="0.5" fill="var(--color-error)" />
          </svg>
          <span className="text-[10px] text-[var(--color-error)] tracking-wider">
            gateway unreachable
          </span>
        </div>
        <button
          onClick={() => setDismissed(true)}
          className="p-1.5 -mr-1 text-[var(--color-error)] active:opacity-60"
        >
          <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
            <path
              d="M2 2L8 8M8 2L2 8"
              stroke="currentColor"
              strokeWidth="1"
              strokeLinecap="round"
            />
          </svg>
        </button>
      </div>
    </div>
  );
}
