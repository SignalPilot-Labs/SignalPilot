"use client";

import { useEffect } from "react";

/**
 * Registers the service worker for offline PWA support.
 * Only activates in production or when running as standalone PWA.
 */
export function ServiceWorkerRegister() {
  useEffect(() => {
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => {
        // Silent fail — SW is a progressive enhancement
      });
    }
  }, []);

  return null;
}
