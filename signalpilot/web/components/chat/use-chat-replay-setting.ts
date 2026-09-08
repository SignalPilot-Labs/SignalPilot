"use client";

import { useSyncExternalStore } from "react";

export const CHAT_REPLAY_STORAGE_KEY = "sp:chat-replay-enabled";

const CHANGE_EVENT = "sp:chat-replay-setting-change";

function getSnapshot(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(CHAT_REPLAY_STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

function subscribe(onStoreChange: () => void): () => void {
  const onStorage = (event: StorageEvent) => {
    if (event.key === CHAT_REPLAY_STORAGE_KEY) onStoreChange();
  };
  window.addEventListener("storage", onStorage);
  window.addEventListener(CHANGE_EVENT, onStoreChange);
  return () => {
    window.removeEventListener("storage", onStorage);
    window.removeEventListener(CHANGE_EVENT, onStoreChange);
  };
}

export function setChatReplayEnabled(enabled: boolean): void {
  try {
    if (enabled) {
      window.localStorage.setItem(CHAT_REPLAY_STORAGE_KEY, "true");
    } else {
      window.localStorage.removeItem(CHAT_REPLAY_STORAGE_KEY);
    }
  } catch {
    // Keep the control usable when browser storage is unavailable.
  }
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

/** Browser-only opt-in for the "Replay chat" action. Replay is a demo
 * feature most users never need, so it is off until enabled here; missing
 * or unavailable storage always means disabled. */
export function useChatReplaySetting(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot, () => false);
}
