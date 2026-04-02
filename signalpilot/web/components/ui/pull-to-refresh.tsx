"use client";

import { useRef, useState, useCallback, useEffect } from "react";
import { RefreshCw } from "lucide-react";

interface PullToRefreshProps {
  onRefresh: () => Promise<void> | void;
  children: React.ReactNode;
  threshold?: number;
  disabled?: boolean;
}

export function PullToRefresh({
  onRefresh,
  children,
  threshold = 80,
  disabled = false,
}: PullToRefreshProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const startY = useRef(0);
  const [pullDistance, setPullDistance] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const pulling = useRef(false);

  const isAtTop = useCallback(() => {
    return window.scrollY <= 0;
  }, []);

  const handleTouchStart = useCallback(
    (e: TouchEvent) => {
      if (disabled || refreshing || !isAtTop()) return;
      startY.current = e.touches[0].clientY;
      pulling.current = true;
    },
    [disabled, refreshing, isAtTop]
  );

  const handleTouchMove = useCallback(
    (e: TouchEvent) => {
      if (!pulling.current || disabled || refreshing) return;
      const deltaY = e.touches[0].clientY - startY.current;
      if (deltaY > 0 && isAtTop()) {
        // Dampen the pull — feels more natural
        const dampened = Math.min(deltaY * 0.4, threshold * 1.5);
        setPullDistance(dampened);
        if (dampened > 10) {
          e.preventDefault();
        }
      } else {
        setPullDistance(0);
        pulling.current = false;
      }
    },
    [disabled, refreshing, isAtTop, threshold]
  );

  const handleTouchEnd = useCallback(async () => {
    if (!pulling.current) return;
    pulling.current = false;

    if (pullDistance >= threshold && !refreshing) {
      setRefreshing(true);
      setPullDistance(threshold * 0.5);
      try {
        await onRefresh();
      } finally {
        setRefreshing(false);
        setPullDistance(0);
      }
    } else {
      setPullDistance(0);
    }
  }, [pullDistance, threshold, refreshing, onRefresh]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    el.addEventListener("touchstart", handleTouchStart, { passive: true });
    el.addEventListener("touchmove", handleTouchMove, { passive: false });
    el.addEventListener("touchend", handleTouchEnd, { passive: true });
    return () => {
      el.removeEventListener("touchstart", handleTouchStart);
      el.removeEventListener("touchmove", handleTouchMove);
      el.removeEventListener("touchend", handleTouchEnd);
    };
  }, [handleTouchStart, handleTouchMove, handleTouchEnd]);

  const progress = Math.min(pullDistance / threshold, 1);
  const showIndicator = pullDistance > 10 || refreshing;

  return (
    <div ref={containerRef} className="sm:hidden relative">
      {/* Pull indicator */}
      <div
        className="absolute left-0 right-0 flex items-center justify-center overflow-hidden pointer-events-none z-20 transition-opacity duration-150"
        style={{
          height: showIndicator ? `${Math.max(pullDistance, refreshing ? 40 : 0)}px` : 0,
          opacity: showIndicator ? 1 : 0,
        }}
      >
        <div className="flex items-center gap-2">
          <RefreshCw
            className={`w-4 h-4 text-[var(--color-text-dim)] transition-transform duration-200 ${
              refreshing ? "animate-spin" : ""
            }`}
            style={{
              transform: refreshing
                ? undefined
                : `rotate(${progress * 360}deg) scale(${0.5 + progress * 0.5})`,
            }}
            strokeWidth={1.5}
          />
          {!refreshing && progress >= 1 && (
            <span className="text-[9px] text-[var(--color-text-dim)] tracking-wider uppercase">
              release
            </span>
          )}
          {refreshing && (
            <span className="text-[9px] text-[var(--color-text-dim)] tracking-wider uppercase">
              refreshing...
            </span>
          )}
        </div>
      </div>
      {/* Content with pull offset */}
      <div
        style={{
          transform: showIndicator
            ? `translateY(${Math.max(pullDistance, refreshing ? 40 : 0)}px)`
            : undefined,
          transition: pulling.current ? "none" : "transform 0.2s ease-out",
        }}
      >
        {children}
      </div>
    </div>
  );
}

/**
 * Responsive wrapper — pull-to-refresh on mobile, plain render on desktop.
 * Uses a single render of children to avoid double-mounting effects/API calls.
 */
export function PullToRefreshWrapper({
  onRefresh,
  children,
  threshold = 80,
  disabled = false,
}: PullToRefreshProps) {
  const [isMobile, setIsMobile] = useState(false);

  useEffect(() => {
    function check() {
      setIsMobile(window.innerWidth < 768);
    }
    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, []);

  if (!isMobile) {
    return <>{children}</>;
  }

  return (
    <PullToRefresh onRefresh={onRefresh} threshold={threshold} disabled={disabled}>
      {children}
    </PullToRefresh>
  );
}
