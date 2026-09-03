"use client";

import { useEffect, useState } from "react";

/**
 * A boolean that turns on immediately but lingers for `delayMs` after the
 * input turns off. Lets a caret or live flag fade out instead of vanishing
 * on the exact frame the last token arrives.
 */
export function useSettled(value: boolean, delayMs: number): boolean {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    if (value) {
      setSettled(true);
      return;
    }
    const timer = setTimeout(() => setSettled(false), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return value || settled;
}
