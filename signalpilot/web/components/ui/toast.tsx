"use client";

import { createContext, useContext, useState, useCallback, useEffect, type ReactNode } from "react";
import { useTierBranding } from "@/lib/hooks/use-tier-branding";

interface Toast {
  id: string;
  message: string;
  type: "success" | "error" | "info";
  duration?: number;
}

interface ToastContextValue {
  toast: (message: string, type?: Toast["type"], duration?: number) => void;
}

const ToastContext = createContext<ToastContextValue>({
  toast: () => {},
});

export function useToast() {
  return useContext(ToastContext);
}

// Left-edge color literals for paid tiers. Tailwind has no side-specific border-color
// shorthand that works with opacity modifiers, so these must be full literal strings
// (not assembled from TIER_BRANDS tokens) to satisfy JIT. Color semantics mirror accentText.
const TIER_LEFT_BORDER: Record<"pro" | "team" | "enterprise", string> = {
  pro:        "border-l-2 border-l-indigo-400/60",
  team:       "border-l-2 border-l-violet-400/60",
  enterprise: "border-l-2 border-l-amber-300/60",
};

function ToastItem({ toast, onRemove }: { toast: Toast; onRemove: (id: string) => void }) {
  const b = useTierBranding();
  const [exiting, setExiting] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => {
      setExiting(true);
      setTimeout(() => onRemove(toast.id), 200);
    }, toast.duration || 3000);
    return () => clearTimeout(timer);
  }, [toast, onRemove]);

  const icons: Record<string, ReactNode> = {
    success: (
      <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
        <rect x="0.5" y="0.5" width="11" height="11" stroke="var(--color-success)" strokeWidth="1" />
        <path d="M3 6L5 8L9 4" stroke="var(--color-success)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
    error: (
      <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
        <rect x="0.5" y="0.5" width="11" height="11" stroke="var(--color-error)" strokeWidth="1" />
        <path d="M4 4L8 8M8 4L4 8" stroke="var(--color-error)" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    ),
    info: (
      <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
        <rect x="0.5" y="0.5" width="11" height="11" stroke="var(--color-text-dim)" strokeWidth="1" />
        <line x1="6" y1="5" x2="6" y2="8" stroke="var(--color-text-dim)" strokeWidth="1.5" strokeLinecap="round" />
        <circle cx="6" cy="3.5" r="0.75" fill="var(--color-text-dim)" />
      </svg>
    ),
  };

  const borderColors: Record<string, string> = {
    success: "border-[var(--color-success)]/20",
    error: "border-[var(--color-error)]/20",
    info: "border-[var(--color-border)]",
  };

  const tierLeftClass =
    b.enabled && b.tier !== "free"
      ? TIER_LEFT_BORDER[b.tier as "pro" | "team" | "enterprise"]
      : "";

  return (
    <div
      className={`flex items-center gap-3 px-4 py-3 bg-[var(--color-bg-card)] border ${borderColors[toast.type]} ${tierLeftClass} shadow-lg ${
        exiting ? "animate-slide-out-right" : "animate-slide-in-right"
      }`}
    >
      {icons[toast.type]}
      <span className="text-[13px] text-[var(--color-text-muted)] tracking-wide">{toast.message}</span>
      <button
        onClick={() => {
          setExiting(true);
          setTimeout(() => onRemove(toast.id), 200);
        }}
        className="ml-auto text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors"
        aria-label="Dismiss notification"
      >
        <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
          <path d="M2 2L8 8M8 2L2 8" stroke="currentColor" strokeWidth="1" strokeLinecap="round" />
        </svg>
      </button>
    </div>
  );
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const addToast = useCallback((message: string, type: Toast["type"] = "info", duration = 3000) => {
    const id = `${Date.now()}-${Math.random()}`;
    setToasts((prev) => [...prev, { id, message, type, duration }]);
  }, []);

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  return (
    <ToastContext.Provider value={{ toast: addToast }}>
      {children}
      {/* Toast container */}
      <div className="fixed bottom-4 right-4 z-[90] space-y-2 max-w-sm" role="status" aria-live="polite">
        {toasts.map((t) => (
          <ToastItem key={t.id} toast={t} onRemove={removeToast} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}
