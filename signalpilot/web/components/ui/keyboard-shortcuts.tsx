"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

const NAV_SHORTCUTS = [
  { key: "1", label: "dashboard", path: "/dashboard" },
  { key: "2", label: "query", path: "/query" },
  { key: "3", label: "schema", path: "/schema" },
  { key: "4", label: "sandboxes", path: "/sandboxes" },
  { key: "5", label: "connections", path: "/connections" },
  { key: "6", label: "health", path: "/health" },
  { key: "7", label: "audit", path: "/audit" },
  { key: "8", label: "settings", path: "/settings" },
];

const ACTION_SHORTCUTS = [
  { key: "K", label: "command palette", modifier: "ctrl" },
  { key: "enter", label: "execute query / run code", modifier: "ctrl" },
  { key: "S", label: "save settings", modifier: "ctrl" },
  { key: "?", label: "show this dialog", modifier: "" },
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
        const shortcut = NAV_SHORTCUTS.find((s) => s.key === e.key);
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
      className="fixed inset-0 z-[100] flex items-end sm:items-center justify-center bg-black/70 px-0 sm:px-4"
      onClick={() => setShowHelp(false)}
    >
      <div
        className="bg-[var(--color-bg-card)] border border-[var(--color-border)] shadow-2xl w-full sm:w-80 max-h-[85vh] overflow-y-auto animate-scale-in safe-area-bottom"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-5 py-3 border-b border-[var(--color-border)] flex items-center justify-between">
          <div className="flex items-center gap-2">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <rect x="1" y="1" width="12" height="12" rx="0" stroke="var(--color-text-dim)" strokeWidth="1" />
              <rect x="4" y="5" width="6" height="4" rx="0" fill="var(--color-text-dim)" opacity="0.4" />
            </svg>
            <span className="text-[10px] uppercase tracking-[0.15em] text-[var(--color-text-dim)]">
              keyboard shortcuts
            </span>
          </div>
          <kbd className="px-1.5 py-0.5 bg-[var(--color-bg)] border border-[var(--color-border)] text-[9px] font-mono text-[var(--color-text-dim)]">
            esc
          </kbd>
        </div>

        {/* Navigation */}
        <div className="px-5 py-3">
          <p className="text-[9px] text-[var(--color-text-dim)] uppercase tracking-[0.15em] mb-2">navigation</p>
          <div className="space-y-0.5">
            {NAV_SHORTCUTS.map((s) => (
              <div key={s.key} className="flex items-center justify-between py-1.5 group">
                <span className="text-xs text-[var(--color-text-muted)] group-hover:text-[var(--color-text)] transition-colors tracking-wide">{s.label}</span>
                <kbd className="px-2 py-0.5 bg-[var(--color-bg)] border border-[var(--color-border)] text-[10px] font-mono text-[var(--color-text-dim)] tabular-nums">
                  ctrl+{s.key}
                </kbd>
              </div>
            ))}
          </div>
        </div>

        {/* Actions */}
        <div className="px-5 py-3 border-t border-[var(--color-border)]">
          <p className="text-[9px] text-[var(--color-text-dim)] uppercase tracking-[0.15em] mb-2">actions</p>
          <div className="space-y-0.5">
            {ACTION_SHORTCUTS.map((s) => (
              <div key={s.key} className="flex items-center justify-between py-1.5">
                <span className="text-xs text-[var(--color-text-muted)] tracking-wide">{s.label}</span>
                <kbd className="px-2 py-0.5 bg-[var(--color-bg)] border border-[var(--color-border)] text-[10px] font-mono text-[var(--color-text-dim)]">
                  {s.modifier ? `${s.modifier}+` : ""}{s.key}
                </kbd>
              </div>
            ))}
          </div>
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-[var(--color-border)]">
          <p className="text-[9px] text-[var(--color-text-dim)] text-center tracking-wider">
            press <kbd className="px-1 py-0.5 bg-[var(--color-bg)] border border-[var(--color-border)] text-[9px] font-mono mx-0.5">?</kbd> or <kbd className="px-1 py-0.5 bg-[var(--color-bg)] border border-[var(--color-border)] text-[9px] font-mono mx-0.5">esc</kbd> to close
          </p>
        </div>
      </div>
    </div>
  );
}
