"use client";

import { useEffect, useState, useCallback, useMemo, useRef } from "react";
import { useRouter } from "next/navigation";

interface CommandItem {
  id: string;
  label: string;
  description: string;
  shortcut?: string;
  action: () => void;
  icon: React.ReactNode;
  category: string;
}

function CommandIcon({ type }: { type: string }) {
  const iconMap: Record<string, React.ReactNode> = {
    nav: (
      <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
        <path d="M2 6H10M7 3L10 6L7 9" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
    action: (
      <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
        <path d="M6 2V10M2 6H10" stroke="currentColor" strokeWidth="1" strokeLinecap="round" />
      </svg>
    ),
    search: (
      <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
        <circle cx="5" cy="5" r="3.5" stroke="currentColor" strokeWidth="1" />
        <path d="M8 8L10.5 10.5" stroke="currentColor" strokeWidth="1" strokeLinecap="round" />
      </svg>
    ),
  };
  return <span className="text-[var(--color-text-dim)]">{iconMap[type] || iconMap.nav}</span>;
}

export function CommandPalette() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const commands: CommandItem[] = useMemo(() => [
    // Navigation
    { id: "nav-dashboard", label: "Dashboard", description: "Overview and metrics", shortcut: "ctrl+1", action: () => router.push("/dashboard"), icon: <CommandIcon type="nav" />, category: "navigation" },
    { id: "nav-query", label: "Query Explorer", description: "Governed SQL queries", shortcut: "ctrl+2", action: () => router.push("/query"), icon: <CommandIcon type="nav" />, category: "navigation" },
    { id: "nav-schema", label: "Schema Explorer", description: "Browse tables and columns", shortcut: "ctrl+3", action: () => router.push("/schema"), icon: <CommandIcon type="nav" />, category: "navigation" },
    { id: "nav-sandboxes", label: "Sandboxes", description: "Firecracker microVMs", shortcut: "ctrl+4", action: () => router.push("/sandboxes"), icon: <CommandIcon type="nav" />, category: "navigation" },
    { id: "nav-connections", label: "Connections", description: "Database connections", shortcut: "ctrl+5", action: () => router.push("/connections"), icon: <CommandIcon type="nav" />, category: "navigation" },
    { id: "nav-health", label: "Health Monitoring", description: "Connection health and latency", shortcut: "ctrl+6", action: () => router.push("/health"), icon: <CommandIcon type="nav" />, category: "navigation" },
    { id: "nav-audit", label: "Audit Log", description: "Compliance audit trail", shortcut: "ctrl+7", action: () => router.push("/audit"), icon: <CommandIcon type="nav" />, category: "navigation" },
    { id: "nav-settings", label: "Settings", description: "Instance configuration", shortcut: "ctrl+8", action: () => router.push("/settings"), icon: <CommandIcon type="nav" />, category: "navigation" },
    // Actions
    { id: "action-new-sandbox", label: "Create Sandbox", description: "Spin up a new microVM", action: () => router.push("/sandboxes"), icon: <CommandIcon type="action" />, category: "actions" },
    { id: "action-new-connection", label: "Add Connection", description: "Configure a new database", action: () => router.push("/connections"), icon: <CommandIcon type="action" />, category: "actions" },
    { id: "action-export-audit", label: "Export Audit Log", description: "Download compliance data", action: () => router.push("/audit"), icon: <CommandIcon type="action" />, category: "actions" },
  ], [router]);

  const filtered = useMemo(() => {
    if (!query) return commands;
    const lower = query.toLowerCase();
    return commands.filter(
      (cmd) =>
        cmd.label.toLowerCase().includes(lower) ||
        cmd.description.toLowerCase().includes(lower) ||
        cmd.category.includes(lower)
    );
  }, [query, commands]);

  const groupedCommands = useMemo(() => {
    const groups: Record<string, CommandItem[]> = {};
    filtered.forEach((cmd) => {
      if (!groups[cmd.category]) groups[cmd.category] = [];
      groups[cmd.category].push(cmd);
    });
    return groups;
  }, [filtered]);

  useEffect(() => {
    setSelectedIndex(0);
  }, [query]);

  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    // Open with cmd+k or ctrl+k
    if ((e.metaKey || e.ctrlKey) && e.key === "k") {
      e.preventDefault();
      setOpen((prev) => !prev);
      return;
    }
  }, []);

  useEffect(() => {
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);

  useEffect(() => {
    if (open) {
      setQuery("");
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  function handleSelect(cmd: CommandItem) {
    setOpen(false);
    cmd.action();
  }

  function handleInputKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape") {
      setOpen(false);
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIndex((prev) => Math.min(prev + 1, filtered.length - 1));
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIndex((prev) => Math.max(prev - 1, 0));
    }
    if (e.key === "Enter" && filtered[selectedIndex]) {
      handleSelect(filtered[selectedIndex]);
    }
  }

  // Scroll selected item into view
  useEffect(() => {
    if (listRef.current) {
      const selected = listRef.current.querySelector("[data-selected='true']");
      selected?.scrollIntoView({ block: "nearest" });
    }
  }, [selectedIndex]);

  if (!open) return null;

  let flatIndex = -1;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-start justify-center pt-[20vh] bg-black/70"
      onClick={() => setOpen(false)}
    >
      <div
        className="w-[480px] bg-[var(--color-bg-card)] border border-[var(--color-border)] shadow-2xl animate-scale-in"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Search input */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-[var(--color-border)]">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" className="flex-shrink-0">
            <circle cx="6" cy="6" r="4.5" stroke="var(--color-text-dim)" strokeWidth="1" />
            <path d="M10 10L13 13" stroke="var(--color-text-dim)" strokeWidth="1" strokeLinecap="round" />
          </svg>
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleInputKeyDown}
            placeholder="search commands..."
            className="flex-1 bg-transparent text-xs text-[var(--color-text)] placeholder:text-[var(--color-text-dim)] focus:outline-none tracking-wide"
          />
          <kbd className="px-1.5 py-0.5 bg-[var(--color-bg)] border border-[var(--color-border)] text-[9px] font-mono text-[var(--color-text-dim)]">
            esc
          </kbd>
        </div>

        {/* Results */}
        <div ref={listRef} className="max-h-80 overflow-auto py-2">
          {filtered.length === 0 ? (
            <div className="px-4 py-8 text-center">
              <p className="text-xs text-[var(--color-text-dim)] tracking-wider">
                no results for &ldquo;{query}&rdquo;
              </p>
            </div>
          ) : (
            Object.entries(groupedCommands).map(([category, items]) => (
              <div key={category}>
                <div className="px-4 py-1.5">
                  <span className="text-[9px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">
                    {category}
                  </span>
                </div>
                {items.map((cmd) => {
                  flatIndex++;
                  const isSelected = flatIndex === selectedIndex;
                  return (
                    <button
                      key={cmd.id}
                      data-selected={isSelected}
                      onClick={() => handleSelect(cmd)}
                      className={`w-full flex items-center gap-3 px-4 py-2 text-left transition-colors ${
                        isSelected ? "bg-[var(--color-bg-hover)]" : "hover:bg-[var(--color-bg-hover)]"
                      }`}
                    >
                      {cmd.icon}
                      <div className="flex-1 min-w-0">
                        <span className="text-xs text-[var(--color-text-muted)] tracking-wide">{cmd.label}</span>
                        <span className="ml-2 text-[10px] text-[var(--color-text-dim)] tracking-wider">{cmd.description}</span>
                      </div>
                      {cmd.shortcut && (
                        <kbd className="px-1.5 py-0.5 bg-[var(--color-bg)] border border-[var(--color-border)] text-[9px] font-mono text-[var(--color-text-dim)] flex-shrink-0">
                          {cmd.shortcut}
                        </kbd>
                      )}
                    </button>
                  );
                })}
              </div>
            ))
          )}
        </div>

        {/* Footer */}
        <div className="px-4 py-2 border-t border-[var(--color-border)] flex items-center justify-between">
          <div className="flex items-center gap-3 text-[9px] text-[var(--color-text-dim)] tracking-wider">
            <span className="flex items-center gap-1">
              <kbd className="px-1 py-0.5 bg-[var(--color-bg)] border border-[var(--color-border)] text-[9px] font-mono">↑↓</kbd>
              navigate
            </span>
            <span className="flex items-center gap-1">
              <kbd className="px-1 py-0.5 bg-[var(--color-bg)] border border-[var(--color-border)] text-[9px] font-mono">↵</kbd>
              select
            </span>
          </div>
          <span className="text-[9px] text-[var(--color-text-dim)] tracking-wider">
            {filtered.length} command{filtered.length !== 1 ? "s" : ""}
          </span>
        </div>
      </div>
    </div>
  );
}
