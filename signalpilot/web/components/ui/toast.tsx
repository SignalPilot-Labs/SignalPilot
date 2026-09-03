"use client";

import { createContext, useContext, useState, useCallback, useEffect, type ReactNode } from "react";
import { useTierBranding } from "~/lib/hooks/use-tier-branding";

export type ToastType = "success" | "error" | "info" | "warning";

/** An inline action on the toast ("Undo"). The toast closes after it runs. */
export type ToastAction = { label: string; onClick: () => void };

interface Toast {
  id: string;
  message: string;
  type: ToastType;
  duration?: number;
  action?: ToastAction;
}

interface ToastContextValue {
  toast: (message: string, type?: ToastType, duration?: number, action?: ToastAction) => void;
}

const ToastContext = createContext<ToastContextValue>({
  toast: () => {},
});

export function useToast() {
  return useContext(ToastContext);
}

// Left-edge color literals for paid tiers. Full literal strings required to satisfy
// Tailwind JIT — do not assemble from brand tokens. Color semantics mirror accentText.
const TIER_LEFT_BORDER: Record<"pro" | "team" | "enterprise", string> = {
  // Pro: use border-active (#444) — distinct from text (#999) so it reads as deliberate accent.
  pro:        "border-l-2 border-l-[var(--color-border-active)]",
  team:       "border-l-2 border-l-blue-400/60",
  enterprise: "border-l-2 border-l-[var(--color-success)]",
};

function ToastItem({ toast, onRemove }: { toast: Toast; onRemove: (id: string) => void }) {
  const b = useTierBranding();
  const [exiting, setExiting] = useState(false);

  const dismiss = useCallback(() => {
    setExiting(true);
    setTimeout(() => onRemove(toast.id), 200);
  }, [onRemove, toast.id]);

  useEffect(() => {
    const timer = setTimeout(dismiss, toast.duration || 3000);
    return () => clearTimeout(timer);
  }, [toast, dismiss]);

  const icons: Record<ToastType, ReactNode> = {
    success: (
      <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
        <rect x="0.5" y="0.5" width="11" height="11" rx="3" stroke="var(--color-success)" strokeWidth="1" />
        <path d="M3 6L5 8L9 4" stroke="var(--color-success)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
    error: (
      <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
        <rect x="0.5" y="0.5" width="11" height="11" rx="3" stroke="var(--color-error)" strokeWidth="1" />
        <path d="M4 4L8 8M8 4L4 8" stroke="var(--color-error)" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    ),
    warning: (
      <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
        <path d="M6 1.2L11 10.5H1L6 1.2Z" stroke="var(--color-warning)" strokeWidth="1" strokeLinejoin="round" />
        <line x1="6" y1="4.5" x2="6" y2="7.2" stroke="var(--color-warning)" strokeWidth="1.5" strokeLinecap="round" />
        <circle cx="6" cy="8.9" r="0.7" fill="var(--color-warning)" />
      </svg>
    ),
    info: (
      <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
        <rect x="0.5" y="0.5" width="11" height="11" rx="3" stroke="var(--color-text-dim)" strokeWidth="1" />
        <line x1="6" y1="5" x2="6" y2="8" stroke="var(--color-text-dim)" strokeWidth="1.5" strokeLinecap="round" />
        <circle cx="6" cy="3.5" r="0.75" fill="var(--color-text-dim)" />
      </svg>
    ),
  };

  const borderColors: Record<ToastType, string> = {
    success: "border-[var(--color-success)]/20",
    error: "border-[var(--color-error)]/20",
    warning: "border-[var(--color-warning)]/30",
    info: "border-[var(--color-border)]",
  };

  const tierLeftClass =
    b.enabled && b.tier !== "free"
      ? TIER_LEFT_BORDER[b.tier as "pro" | "team" | "enterprise"]
      : "";

  return (
    <div
      data-testid="toast"
      data-toast-type={toast.type}
      className={`flex items-center gap-3 px-4 py-3 rounded-[14px] bg-[var(--color-bg-card)] border ${borderColors[toast.type]} ${tierLeftClass} shadow-lg ${
        exiting ? "animate-slide-out-right" : "animate-slide-in-right"
      }`}
    >
      {icons[toast.type]}
      <span className="text-[13px] leading-none text-[var(--color-text-muted)]">{toast.message}</span>
      {toast.action && (
        <button
          type="button"
          data-testid="toast-action"
          onClick={() => {
            toast.action?.onClick();
            dismiss();
          }}
          className="ml-1 rounded-[8px] border border-[var(--color-border)] px-2 py-1 text-[12px] font-medium text-[var(--color-text)] transition-colors hover:border-[var(--color-border-hover)] hover:bg-[var(--color-bg-hover)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-text)]"
        >
          {toast.action.label}
        </button>
      )}
      <button
        onClick={dismiss}
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

  const addToast = useCallback(
    (message: string, type: ToastType = "info", duration = 3000, action?: ToastAction) => {
      const id = `${Date.now()}-${Math.random()}`;
      setToasts((prev) => [...prev, { id, message, type, duration, action }]);
    },
    [],
  );

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
