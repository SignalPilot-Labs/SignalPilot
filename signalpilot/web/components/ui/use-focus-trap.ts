"use client";

import { useEffect, type RefObject } from "react";

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"]):not([disabled])';

function focusables(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    (el) => el.offsetParent !== null || el === document.activeElement,
  );
}

/**
 * Keeps Tab / Shift+Tab inside `ref` while `active`. Listens on the
 * container itself, so a dialog nested inside another (a confirm over a
 * drawer) wins: its handler runs first and stops propagation. Focus-return
 * stays the caller's job (they already restore it on close).
 */
export function useFocusTrap(ref: RefObject<HTMLElement | null>, active: boolean) {
  useEffect(() => {
    if (!active) return;
    const root = ref.current;
    if (!root) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Tab") return;
      const items = focusables(root);
      if (items.length === 0) {
        event.preventDefault();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const current = document.activeElement as HTMLElement | null;
      if (event.shiftKey && (current === first || !root.contains(current))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (current === last || !root.contains(current))) {
        event.preventDefault();
        first.focus();
      }
      event.stopPropagation();
    };
    root.addEventListener("keydown", onKey);
    // If focus is outside the dialog when it opens, pull it in.
    if (!root.contains(document.activeElement)) focusables(root)[0]?.focus();
    return () => root.removeEventListener("keydown", onKey);
  }, [ref, active]);
}
