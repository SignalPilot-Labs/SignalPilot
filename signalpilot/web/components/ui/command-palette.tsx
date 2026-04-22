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

/* ── Fuzzy match with highlighted spans ── */
function fuzzyMatch(query: string, text: string): { matches: boolean; indices: number[] } {
  const lower = text.toLowerCase();
  const q = query.toLowerCase();
  const indices: number[] = [];
  let qi = 0;
  for (let i = 0; i < lower.length && qi < q.length; i++) {
    if (lower[i] === q[qi]) {
      indices.push(i);
      qi++;
    }
  }
  return { matches: qi === q.length, indices };
}

function HighlightedText({ text, indices }: { text: string; indices: number[] }) {
  const set = new Set(indices);
  return (
    <span>
      {text.split("").map((char, i) =>
        set.has(i) ? (
          <span key={i} className="text-[var(--color-text)]">{char}</span>
        ) : (
          <span key={i}>{char}</span>
        )
      )}
    </span>
  );
}

/* ── SVG icons ── */
function IconNav() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
      <path d="M2 6H10M7 3L10 6L7 9" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function IconAction() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
      <path d="M6 2V10M2 6H10" stroke="currentColor" strokeWidth="1" strokeLinecap="round" />
    </svg>
  );
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
    { id: "nav-dashboard", label: "dashboard", description: "overview and metrics", shortcut: "^1", action: () => router.push("/dashboard"), icon: <IconNav />, category: "navigate" },
    { id: "nav-query", label: "query explorer", description: "governed sql queries", shortcut: "^2", action: () => router.push("/query"), icon: <IconNav />, category: "navigate" },
    { id: "nav-schema", label: "schema explorer", description: "browse tables and columns", shortcut: "^3", action: () => router.push("/schema"), icon: <IconNav />, category: "navigate" },
    { id: "nav-sandboxes", label: "sandboxes", description: "gvisor sandboxes", shortcut: "^4", action: () => router.push("/sandboxes"), icon: <IconNav />, category: "navigate" },
    { id: "nav-connections", label: "connections", description: "database connections", shortcut: "^5", action: () => router.push("/connections"), icon: <IconNav />, category: "navigate" },
    { id: "nav-health", label: "health monitoring", description: "connection health and latency", shortcut: "^6", action: () => router.push("/health"), icon: <IconNav />, category: "navigate" },
    { id: "nav-audit", label: "audit log", description: "compliance audit trail", shortcut: "^7", action: () => router.push("/audit"), icon: <IconNav />, category: "navigate" },
    { id: "nav-settings", label: "settings", description: "instance configuration", shortcut: "^8", action: () => router.push("/settings"), icon: <IconNav />, category: "navigate" },
    // Actions
    { id: "action-new-sandbox", label: "create sandbox", description: "spin up a new sandbox", action: () => router.push("/sandboxes"), icon: <IconAction />, category: "actions" },
    { id: "action-new-connection", label: "add connection", description: "configure a new database", action: () => router.push("/connections"), icon: <IconAction />, category: "actions" },
    { id: "action-export-audit", label: "export audit log", description: "download compliance data", action: () => router.push("/audit"), icon: <IconAction />, category: "actions" },
  ], [router]);

  const filtered = useMemo(() => {
    if (!query) return commands.map((cmd) => ({ cmd, labelIndices: [] as number[], descIndices: [] as number[] }));
    return commands
      .map((cmd) => {
        const labelMatch = fuzzyMatch(query, cmd.label);
        const descMatch = fuzzyMatch(query, cmd.description);
        return {
          cmd,
          labelIndices: labelMatch.indices,
          descIndices: descMatch.indices,
          matches: labelMatch.matches || descMatch.matches,
        };
      })
      .filter((r) => r.matches);
  }, [query, commands]);

  const groupedCommands = useMemo(() => {
    const groups: Record<string, typeof filtered> = {};
    filtered.forEach((item) => {
      if (!groups[item.cmd.category]) groups[item.cmd.category] = [];
      groups[item.cmd.category].push(item);
    });
    return groups;
  }, [filtered]);

  useEffect(() => {
    setSelectedIndex(0);
  }, [query]);

  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "k") {
      e.preventDefault();
      setOpen((prev) => !prev);
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
    setQuery("");
    cmd.action();
  }

  function handleInputKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape") {
      setOpen(false);
      setQuery("");
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
      handleSelect(filtered[selectedIndex].cmd);
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
      className="fixed inset-0 z-[100] flex items-start justify-center pt-[18vh]"
      onClick={() => { setOpen(false); setQuery(""); }}
    >
      {/* Backdrop with blur */}
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />

      {/* Palette */}
      <div
        className="relative w-[520px] bg-[var(--color-bg)] border border-[var(--color-border-hover)] shadow-2xl animate-scale-in overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Top accent line */}
        <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-[var(--color-text-dim)] to-transparent opacity-30" />

        {/* Search input */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-[var(--color-border)]">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" className="flex-shrink-0 text-[var(--color-text-dim)]">
            <circle cx="6" cy="6" r="4.5" stroke="currentColor" strokeWidth="1" />
            <path d="M9.5 9.5L12.5 12.5" stroke="currentColor" strokeWidth="1" strokeLinecap="round" />
          </svg>
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleInputKeyDown}
            placeholder="type a command or search..."
            className="flex-1 bg-transparent text-xs text-[var(--color-text)] placeholder:text-[var(--color-text-dim)] focus:outline-none tracking-wide"
            autoComplete="off"
            spellCheck={false}
          />
          <kbd className="px-1.5 py-0.5 bg-[var(--color-bg-card)] border border-[var(--color-border)] text-[10px] font-mono text-[var(--color-text-dim)]">
            esc
          </kbd>
        </div>

        {/* Results */}
        <div ref={listRef} className="max-h-80 overflow-auto py-1">
          {filtered.length === 0 ? (
            <div className="px-4 py-10 text-center">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" className="mx-auto mb-2 text-[var(--color-text-dim)] opacity-40">
                <circle cx="10" cy="10" r="7" stroke="currentColor" strokeWidth="1.5" />
                <path d="M15 15L21 21" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                <path d="M7 10H13" stroke="currentColor" strokeWidth="1" strokeLinecap="round" />
              </svg>
              <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider">
                no results for &ldquo;{query}&rdquo;
              </p>
            </div>
          ) : (
            Object.entries(groupedCommands).map(([category, items]) => (
              <div key={category}>
                <div className="px-4 pt-2.5 pb-1">
                  <span className="text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">
                    {category}
                  </span>
                </div>
                {items.map((item) => {
                  flatIndex++;
                  const isSelected = flatIndex === selectedIndex;
                  return (
                    <button
                      key={item.cmd.id}
                      data-selected={isSelected}
                      onClick={() => handleSelect(item.cmd)}
                      onMouseEnter={() => setSelectedIndex(flatIndex)}
                      className={`w-full flex items-center gap-3 px-4 py-2 text-left transition-colors ${
                        isSelected
                          ? "bg-[var(--color-bg-hover)] text-[var(--color-text)]"
                          : "text-[var(--color-text-muted)] hover:bg-[var(--color-bg-hover)]"
                      }`}
                    >
                      <span className={`flex-shrink-0 ${isSelected ? "text-[var(--color-success)]" : "text-[var(--color-text-dim)]"}`}>
                        {item.cmd.icon}
                      </span>
                      <div className="flex-1 min-w-0">
                        <span className="text-xs tracking-wide">
                          {query ? <HighlightedText text={item.cmd.label} indices={item.labelIndices} /> : item.cmd.label}
                        </span>
                        <span className="ml-2 text-[12px] text-[var(--color-text-dim)] tracking-wider">
                          {query ? <HighlightedText text={item.cmd.description} indices={item.descIndices} /> : item.cmd.description}
                        </span>
                      </div>
                      {item.cmd.shortcut && (
                        <kbd className="px-1.5 py-0.5 bg-[var(--color-bg)] border border-[var(--color-border)] text-[10px] font-mono text-[var(--color-text-dim)] flex-shrink-0">
                          {item.cmd.shortcut}
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
        <div className="flex items-center justify-between px-4 py-2 border-t border-[var(--color-border)] text-[11px] text-[var(--color-text-dim)] tracking-wider">
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1">
              <kbd className="px-1 py-0.5 bg-[var(--color-bg-card)] border border-[var(--color-border)] text-[10px] font-mono">↑↓</kbd>
              navigate
            </span>
            <span className="flex items-center gap-1">
              <kbd className="px-1 py-0.5 bg-[var(--color-bg-card)] border border-[var(--color-border)] text-[10px] font-mono">↵</kbd>
              select
            </span>
          </div>
          <span>{filtered.length} result{filtered.length !== 1 ? "s" : ""}</span>
        </div>
      </div>
    </div>
  );
}
