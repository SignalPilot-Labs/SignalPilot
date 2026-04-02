"use client";

import {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  useRef,
  type ReactNode,
} from "react";

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

function ToastItem({
  toast,
  onRemove,
}: {
  toast: Toast;
  onRemove: (id: string) => void;
}) {
  const [exiting, setExiting] = useState(false);
  const [swipeX, setSwipeX] = useState(0);
  const touchStartX = useRef(0);
  const itemRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const timer = setTimeout(() => {
      setExiting(true);
      setTimeout(() => onRemove(toast.id), 200);
    }, toast.duration || 3000);
    return () => clearTimeout(timer);
  }, [toast, onRemove]);

  function handleTouchStart(e: React.TouchEvent) {
    touchStartX.current = e.touches[0].clientX;
  }

  function handleTouchMove(e: React.TouchEvent) {
    const delta = e.touches[0].clientX - touchStartX.current;
    if (delta > 0) setSwipeX(delta); // only swipe right to dismiss
  }

  function handleTouchEnd() {
    if (swipeX > 80) {
      setExiting(true);
      setTimeout(() => onRemove(toast.id), 200);
    } else {
      setSwipeX(0);
    }
  }

  const icons: Record<string, ReactNode> = {
    success: (
      <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
        <rect
          x="0.5"
          y="0.5"
          width="11"
          height="11"
          stroke="var(--color-success)"
          strokeWidth="1"
        />
        <path
          d="M3 6L5 8L9 4"
          stroke="var(--color-success)"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    ),
    error: (
      <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
        <rect
          x="0.5"
          y="0.5"
          width="11"
          height="11"
          stroke="var(--color-error)"
          strokeWidth="1"
        />
        <path
          d="M4 4L8 8M8 4L4 8"
          stroke="var(--color-error)"
          strokeWidth="1.5"
          strokeLinecap="round"
        />
      </svg>
    ),
    info: (
      <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
        <rect
          x="0.5"
          y="0.5"
          width="11"
          height="11"
          stroke="var(--color-text-dim)"
          strokeWidth="1"
        />
        <line
          x1="6"
          y1="5"
          x2="6"
          y2="8"
          stroke="var(--color-text-dim)"
          strokeWidth="1.5"
          strokeLinecap="round"
        />
        <circle cx="6" cy="3.5" r="0.75" fill="var(--color-text-dim)" />
      </svg>
    ),
  };

  const borderColors: Record<string, string> = {
    success: "border-[var(--color-success)]/20",
    error: "border-[var(--color-error)]/20",
    info: "border-[var(--color-border)]",
  };

  return (
    <div
      ref={itemRef}
      onTouchStart={handleTouchStart}
      onTouchMove={handleTouchMove}
      onTouchEnd={handleTouchEnd}
      style={{
        transform: swipeX > 0 ? `translateX(${swipeX}px)` : undefined,
        opacity: swipeX > 0 ? 1 - swipeX / 160 : undefined,
      }}
      className={`flex items-center gap-3 px-4 py-3 bg-[var(--color-bg-card)] border ${borderColors[toast.type]} shadow-lg transition-transform ${
        exiting
          ? "animate-slide-out-right"
          : swipeX > 0
            ? ""
            : "animate-slide-in-right"
      }`}
    >
      {icons[toast.type]}
      <span className="text-[13px] text-[var(--color-text-muted)] tracking-wide">
        {toast.message}
      </span>
      <button
        onClick={() => {
          setExiting(true);
          setTimeout(() => onRemove(toast.id), 200);
        }}
        className="ml-auto text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors"
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
  );
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const addToast = useCallback(
    (message: string, type: Toast["type"] = "info", duration = 3000) => {
      const id = `${Date.now()}-${Math.random()}`;
      setToasts((prev) => [...prev, { id, message, type, duration }]);
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
      <div className="fixed bottom-[calc(3.5rem+env(safe-area-inset-bottom,0px)+0.5rem)] sm:bottom-4 right-4 left-4 sm:left-auto z-[90] space-y-2 max-w-sm sm:max-w-sm">
        {toasts.map((t) => (
          <ToastItem key={t.id} toast={t} onRemove={removeToast} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}
