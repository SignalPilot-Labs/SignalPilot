import { atom, useAtomValue } from "jotai";
import { atomWithStorage } from "jotai/utils";
import { init } from "@paralleldrive/cuid2";
import { classifyFile } from "./active-file";
import type { SessionId } from "./kernel/session";
import { store } from "./state/jotai";

const createTabId = init({ length: 8 });
const createSessionId = init({ length: 6 });
const NOTION_THREAD_STORAGE_PREFIX = "sp:notion-thread:";

/**
 * A file tab represents an open file in the editor.
 *
 * INVARIANT: `path` and `sessionId` are IMMUTABLE after creation.
 * This guarantees that saves always target the correct file.
 */
export interface FileTab {
  /** Unique tab identifier */
  id: string;
  /** Absolute file path — IMMUTABLE after creation */
  path: string;
  /** File type */
  type: "raw" | "notebook";
  /** Session ID for notebook tabs — IMMUTABLE after creation */
  sessionId: SessionId | null;
  /** Short display name */
  name: string;
}

// ── Atoms ────────────────────────────────────────────────────────

/** All open tabs — persisted so tabs survive page reloads */
export const openTabsAtom = atomWithStorage<FileTab[]>(
  "sp:open-tabs",
  [],
);

/** ID of the currently active tab */
export const activeTabIdAtom = atomWithStorage<string | null>(
  "sp:active-tab-id",
  null,
);

/** Derived: the currently active tab object */
export const activeTabAtom = atom<FileTab | null>((get) => {
  const tabs = get(openTabsAtom);
  const activeId = get(activeTabIdAtom);
  if (!activeId) {return null;}
  return tabs.find((t) => t.id === activeId) || null;
});

// ── Actions ──────────────────────────────────────────────────────

function normalizePath(path: string): string {
  return path.replace(/\\/g, "/").replace(/^\/+/, "");
}

function isSameNotionPath(candidate: string, trailFile: string): boolean {
  const normalizedCandidate = normalizePath(candidate);
  const normalizedTrailFile = normalizePath(trailFile);
  return (
    normalizedCandidate === normalizedTrailFile ||
    normalizedCandidate.endsWith(`/${normalizedTrailFile}`) ||
    normalizedTrailFile.endsWith(normalizedCandidate)
  );
}

function getNotionSessionIdForPath(path: string): SessionId | null {
  if (typeof window === "undefined") {
    return null;
  }

  const params = new URLSearchParams(window.location.search);
  const trailFile = params.get("file") ?? "";
  if (!trailFile.startsWith("signalpilot-notion-analyses/") || !isSameNotionPath(path, trailFile)) {
    return null;
  }

  const urlSessionId = params.get("session_id");
  if (urlSessionId?.startsWith("session-notion-")) {
    return urlSessionId as SessionId;
  }

  try {
    const storedSessionId = window.localStorage.getItem(`${NOTION_THREAD_STORAGE_PREFIX}${trailFile}`);
    return storedSessionId?.startsWith("session-notion-")
      ? (storedSessionId as SessionId)
      : null;
  } catch {
    return null;
  }
}

/**
 * Open a file in a tab. If the file is already open, activate that tab.
 * Otherwise create a new tab.
 */
export function openFileInTab(path: string, forceRaw?: boolean): FileTab {
  const tabs = store.get(openTabsAtom);
  const notionSessionId = getNotionSessionIdForPath(path);

  // Check if already open
  const existing = tabs.find((t) => t.path === path);
  if (existing) {
    const expectedType = forceRaw ? "raw" : classifyFile(path);
    const correctType = expectedType === "unknown" ? "raw" : expectedType;
    // Fix stale tab type (e.g. notebook stored as raw or vice versa)
    if (forceRaw && existing.type === "notebook") {
      const fixed: FileTab = { ...existing, type: "raw", sessionId: null };
      store.set(openTabsAtom, tabs.map((t) => (t.id === existing.id ? fixed : t)));
      store.set(activeTabIdAtom, fixed.id);
      return fixed;
    }
    if (!forceRaw && existing.type === "raw" && correctType === "notebook") {
      const fixed: FileTab = {
        ...existing,
        type: "notebook",
        sessionId: notionSessionId ?? (`s_${createSessionId()}` as SessionId),
      };
      store.set(openTabsAtom, tabs.map((t) => (t.id === existing.id ? fixed : t)));
      store.set(activeTabIdAtom, fixed.id);
      return fixed;
    }
    if (notionSessionId && existing.type === "notebook" && existing.sessionId !== notionSessionId) {
      const fixed: FileTab = { ...existing, sessionId: notionSessionId };
      store.set(openTabsAtom, tabs.map((t) => (t.id === existing.id ? fixed : t)));
      store.set(activeTabIdAtom, fixed.id);
      return fixed;
    }
    store.set(activeTabIdAtom, existing.id);
    return existing;
  }

  // Create new tab
  const type = forceRaw ? "raw" : classifyFile(path);
  const fileType = type === "unknown" ? "raw" : type;
  const name = path.split(/[/\\]/).pop() || "Untitled";

  const tab: FileTab = {
    id: createTabId(),
    path,
    type: fileType,
    sessionId:
      fileType === "notebook"
        ? (notionSessionId ?? (`s_${createSessionId()}` as SessionId))
        : null,
    name,
  };

  store.set(openTabsAtom, [...tabs, tab]);
  store.set(activeTabIdAtom, tab.id);
  return tab;
}

/**
 * Close a tab. If it was active, activate the nearest neighbor.
 */
export function closeTab(tabId: string): void {
  const tabs = store.get(openTabsAtom);
  const activeId = store.get(activeTabIdAtom);
  const idx = tabs.findIndex((t) => t.id === tabId);

  if (idx === -1) {return;}

  const newTabs = tabs.filter((t) => t.id !== tabId);
  store.set(openTabsAtom, newTabs);

  // If we closed the active tab, activate a neighbor
  if (activeId === tabId) {
    if (newTabs.length === 0) {
      store.set(activeTabIdAtom, null);
    } else {
      const newIdx = Math.min(idx, newTabs.length - 1);
      store.set(activeTabIdAtom, newTabs[newIdx].id);
    }
  }
}

/**
 * Activate a tab by ID.
 */
export function activateTab(tabId: string): void {
  store.set(activeTabIdAtom, tabId);
}

// ── Hooks ────────────────────────────────────────────────────────

export function useOpenTabs() {
  return useAtomValue(openTabsAtom);
}

export function useActiveTab() {
  return useAtomValue(activeTabAtom);
}

export function useActiveTabId() {
  return useAtomValue(activeTabIdAtom);
}
