"use client";

// Portal menu primitive. The menu renders into document.body, so it is never
// trapped in a row's stacking context or clipped by an overflow container.
// Position is taken from the trigger's rect on open and kept on scroll and
// resize. Keyboard: ArrowUp/Down, Home/End, Escape, Tab (closes).

import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type RefObject,
} from "react";
import { createPortal } from "react-dom";

export type MenuItem = {
  label: string;
  onSelect: () => void;
  danger?: boolean;
  disabled?: boolean;
};

type Placement = { top: number; left: number; minWidth: number };

function place(anchor: HTMLElement, menu: HTMLElement | null, align: "start" | "end"): Placement {
  const rect = anchor.getBoundingClientRect();
  const width = Math.max(200, menu?.offsetWidth ?? 200);
  const height = menu?.offsetHeight ?? 0;
  const gap = 4;
  let left = align === "end" ? rect.right - width : rect.left;
  left = Math.max(8, Math.min(left, window.innerWidth - width - 8));
  let top = rect.bottom + gap;
  if (height && top + height > window.innerHeight - 8) top = Math.max(8, rect.top - gap - height);
  return { top, left, minWidth: 200 };
}

/**
 * Controlled popup menu anchored to `anchorRef`. The trigger stays in the
 * caller's markup (it owns aria-haspopup / aria-expanded / aria-controls via
 * the returned id); this component owns the popup.
 */
export function Menu({
  open,
  onClose,
  anchorRef,
  items,
  label,
  align = "end",
  initialIndex = 0,
}: {
  open: boolean;
  onClose: (reason: "select" | "escape" | "outside" | "tab") => void;
  anchorRef: RefObject<HTMLElement | null>;
  items: MenuItem[];
  label: string;
  align?: "start" | "end";
  initialIndex?: number;
}) {
  const id = useId();
  const menuRef = useRef<HTMLDivElement>(null);
  const [placement, setPlacement] = useState<Placement | null>(null);
  const [index, setIndex] = useState(initialIndex);

  const reposition = useCallback(() => {
    if (anchorRef.current) setPlacement(place(anchorRef.current, menuRef.current, align));
  }, [align, anchorRef]);

  useLayoutEffect(() => {
    if (!open) return;
    setIndex(initialIndex);
    reposition();
  }, [open, initialIndex, reposition]);

  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (menuRef.current?.contains(target) || anchorRef.current?.contains(target)) return;
      onClose("outside");
    };
    const onScroll = () => reposition();
    document.addEventListener("mousedown", onDown);
    window.addEventListener("resize", onScroll);
    document.addEventListener("scroll", onScroll, true);
    return () => {
      document.removeEventListener("mousedown", onDown);
      window.removeEventListener("resize", onScroll);
      document.removeEventListener("scroll", onScroll, true);
    };
  }, [open, onClose, anchorRef, reposition]);

  useEffect(() => {
    if (!open) return;
    const item = menuRef.current?.querySelectorAll<HTMLButtonElement>("[role=menuitem]")[index];
    item?.focus();
  }, [open, index, placement]);

  if (!open || typeof document === "undefined") return null;

  const enabledIndexes = items.map((item, i) => (item.disabled ? -1 : i)).filter((i) => i >= 0);
  const step = (delta: number) => {
    if (enabledIndexes.length === 0) return;
    const at = enabledIndexes.indexOf(index);
    const next = enabledIndexes[(at + delta + enabledIndexes.length) % enabledIndexes.length];
    setIndex(next);
  };

  return createPortal(
    <div
      ref={menuRef}
      id={id}
      role="menu"
      aria-label={label}
      data-testid="menu-popup"
      style={placement ? { top: placement.top, left: placement.left, minWidth: placement.minWidth } : { visibility: "hidden" }}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          onClose("escape");
        } else if (event.key === "ArrowDown") {
          event.preventDefault();
          step(1);
        } else if (event.key === "ArrowUp") {
          event.preventDefault();
          step(-1);
        } else if (event.key === "Home") {
          event.preventDefault();
          setIndex(enabledIndexes[0] ?? 0);
        } else if (event.key === "End") {
          event.preventDefault();
          setIndex(enabledIndexes[enabledIndexes.length - 1] ?? 0);
        } else if (event.key === "Tab") {
          onClose("tab");
        }
      }}
      onBlur={(event) => {
        const next = event.relatedTarget as Node | null;
        if (next && (menuRef.current?.contains(next) || anchorRef.current?.contains(next))) return;
        if (next) onClose("tab");
      }}
      className="fixed z-[95] overflow-hidden rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-bg-elevated)] py-1 shadow-2xl shadow-black/40 animate-scale-in"
    >
      {items.map((item) => (
        <button
          key={item.label}
          type="button"
          role="menuitem"
          disabled={item.disabled}
          tabIndex={-1}
          onClick={(event) => {
            event.stopPropagation();
            onClose("select");
            item.onSelect();
          }}
          className={`flex min-h-[40px] w-full items-center px-3.5 text-left text-[12.5px] outline-none transition-colors disabled:opacity-40 focus-visible:bg-[var(--color-bg-hover)] ${
            item.danger
              ? "text-[var(--color-error)] hover:bg-[var(--color-error)]/10"
              : "text-[var(--color-text)] hover:bg-[var(--color-bg-hover)]"
          }`}
        >
          {item.label}
        </button>
      ))}
    </div>,
    document.body,
  );
}

/** Convenience for the common trigger: a button that opens a `Menu`. */
export function useMenuTrigger() {
  const anchorRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const close = useCallback(
    (reason: "select" | "escape" | "outside" | "tab") => {
      setOpen(false);
      if (reason === "escape") anchorRef.current?.focus();
    },
    [],
  );
  return { anchorRef, open, setOpen, close };
}
