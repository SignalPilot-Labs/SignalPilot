"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

const SHORTCUTS = [
  { key: "1", label: "dashboard", path: "/dashboard" },
  { key: "2", label: "query", path: "/query" },
  { key: "3", label: "schema", path: "/schema" },
  { key: "4", label: "sandboxes", path: "/sandboxes" },
  { key: "5", label: "connections", path: "/connections" },
  { key: "6", label: "health", path: "/health" },
  { key: "7", label: "audit", path: "/audit" },
  { key: "8", label: "settings", path: "/settings" },
];

export function KeyboardShortcuts() {
  const router = useRouter();
  const [showHelp, setShowHelp] = useState(false);

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      const target = e.target as HTMLElement;
      if (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT") {
        return;
      }

      if (e.key === "?" && !e.ctrlKey && !e.metaKey) {
        e.preventDefault();
        setShowHelp((prev) => !prev);
        return;
      }

      if (e.key === "Escape" && showHelp) {
        setShowHelp(false);
        return;
      }

      if (e.ctrlKey || e.metaKey) {
        const shortcut = SHORTCUTS.find((s) => s.key === e.key);
        if (shortcut) {
          e.preventDefault();
          router.push(shortcut.path);
        }
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [router, showHelp]);

  if (!showHelp) return null;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70"
      onClick={() => setShowHelp(false)}
    >
      <div
        className="bg-[var(--color-bg-card)] border border-[var(--color-border)] p-6 shadow-2xl w-80"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="text-[10px] uppercase tracking-widest text-[var(--color-text-dim)] mb-4">
          keyboard shortcuts
        </div>
        <div className="space-y-1.5">
          {SHORTCUTS.map((s) => (
            <div key={s.key} className="flex items-center justify-between py-1">
              <span className="text-xs text-[var(--color-text-muted)]">{s.label}</span>
              <kbd className="px-2 py-0.5 bg-[var(--color-bg)] border border-[var(--color-border)] text-[10px] font-mono text-[var(--color-text-dim)]">
                ctrl+{s.key}
              </kbd>
            </div>
          ))}
          <div className="border-t border-[var(--color-border)] pt-2 mt-2 space-y-1.5">
            <div className="flex items-center justify-between py-1">
              <span className="text-xs text-[var(--color-text-muted)]">execute query</span>
              <kbd className="px-2 py-0.5 bg-[var(--color-bg)] border border-[var(--color-border)] text-[10px] font-mono text-[var(--color-text-dim)]">
                ctrl+enter
              </kbd>
            </div>
            <div className="flex items-center justify-between py-1">
              <span className="text-xs text-[var(--color-text-muted)]">show shortcuts</span>
              <kbd className="px-2 py-0.5 bg-[var(--color-bg)] border border-[var(--color-border)] text-[10px] font-mono text-[var(--color-text-dim)]">
                ?
              </kbd>
            </div>
          </div>
        </div>
        <p className="text-[9px] text-[var(--color-text-dim)] mt-4 text-center tracking-wider">
          esc or ? to close
        </p>
      </div>
    </div>
  );
}
