"use client";

import { useSyncExternalStore } from "react";

export const CHAT_TELEMETRY_AVAILABLE =
  process.env.NEXT_PUBLIC_CHAT_TELEMETRY_ENABLED === "true";

export const CHAT_TELEMETRY_STORAGE_KEY = "sp:chat-telemetry-enabled";

const CHANGE_EVENT = "sp:chat-telemetry-setting-change";

function getSnapshot(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(CHAT_TELEMETRY_STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

function subscribe(onStoreChange: () => void): () => void {
  const onStorage = (event: StorageEvent) => {
    if (event.key === CHAT_TELEMETRY_STORAGE_KEY) onStoreChange();
  };
  window.addEventListener("storage", onStorage);
  window.addEventListener(CHANGE_EVENT, onStoreChange);
  return () => {
    window.removeEventListener("storage", onStorage);
    window.removeEventListener(CHANGE_EVENT, onStoreChange);
  };
}

export function setChatTelemetryEnabled(enabled: boolean): void {
  try {
    if (enabled) {
      window.localStorage.setItem(CHAT_TELEMETRY_STORAGE_KEY, "true");
    } else {
      window.localStorage.removeItem(CHAT_TELEMETRY_STORAGE_KEY);
    }
  } catch {
    // Keep the control usable when browser storage is unavailable.
  }
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

/** Browser-only opt-in. Missing or unavailable storage always means disabled. */
export function useChatTelemetrySetting(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot, () => false);
}
