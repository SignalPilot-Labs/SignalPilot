import { atom } from "jotai";
import { init } from "@paralleldrive/cuid2";
import { Logger } from "@/utils/Logger";
import type { TypedString } from "@/utils/typed";
import { updateQueryParams } from "@/utils/urls";
import { KnownQueryParams } from "../constants";
import { store } from "../state/jotai";

export type SessionId = TypedString<"SessionId">;

const createId = init({ length: 6 });

export function generateSessionId(): SessionId {
  return `s_${createId()}` as SessionId;
}

export function generateProjectSessionId(projectDir: string): SessionId {
  let hash = 0;
  for (let i = 0; i < projectDir.length; i++) {
    const char = projectDir.charCodeAt(i);
    hash = ((hash << 5) - hash + char) | 0;
  }
  const hex = Math.abs(hash).toString(36).padStart(6, "0").slice(0, 6);
  return `s_${hex}` as SessionId;
}

export function isSessionId(value: string | null): value is SessionId {
  if (!value) {
    return false;
  }
  return /^s_[\da-z]{6}$/.test(value) || /^session-[A-Za-z0-9][A-Za-z0-9_-]{0,120}$/.test(value);
}

function getProjectDirFromStorage(): string | null {
  try {
    const raw = localStorage.getItem("sp:dbt-project-dir");
    if (raw && raw !== "null") {
      return JSON.parse(raw) as string | null;
    }
  } catch {
    // localStorage may throw in sandboxed iframes
  }
  return null;
}

function isNotebookFileInUrl(): boolean {
  if (typeof window === "undefined") return false;
  const url = new URL(window.location.href);
  const file = url.searchParams.get("file") || "";
  return (
    file.endsWith(".py") || file.endsWith(".md") || file.endsWith(".qmd")
  );
}

function computeInitialSessionId(): SessionId {
  if (typeof window === "undefined") {
    return generateSessionId();
  }

  const url = new URL(window.location.href);
  const id = url.searchParams.get(
    KnownQueryParams.sessionId,
  ) as SessionId | null;
  if (isSessionId(id)) {
    const shouldPreserveSessionId =
      id.startsWith("session-notion-") || url.pathname.startsWith("/notebooks");
    if (!shouldPreserveSessionId) {
      updateQueryParams((params) => {
        if (params.has(KnownQueryParams.kiosk)) {
          return;
        }
        params.delete(KnownQueryParams.sessionId);
      });
    } else {
      updateQueryParams((params) => {
        if (!params.has(KnownQueryParams.sessionId)) {
          params.set(KnownQueryParams.sessionId, id);
        }
        return;
      });
    }
    Logger.debug("Connecting to existing session", { sessionId: id });
    return id;
  }

  if (isNotebookFileInUrl()) {
    const newId = generateSessionId();
    Logger.debug("Notebook file - new session", { sessionId: newId });
    return newId;
  }

  const projectDir = getProjectDirFromStorage();
  if (projectDir) {
    const projectSessionId = generateProjectSessionId(projectDir);
    Logger.debug("Using project session", {
      sessionId: projectSessionId,
      projectDir,
    });
    return projectSessionId;
  }

  return generateSessionId();
}

export const sessionIdAtom = atom<SessionId>(computeInitialSessionId());

export function getSessionId(): SessionId {
  return store.get(sessionIdAtom);
}

export function setSessionId(id: SessionId): void {
  store.set(sessionIdAtom, id);
  Logger.debug("Set session ID", { sessionId: id });
}

export function regenerateSessionId(): SessionId {
  const id = generateSessionId();
  store.set(sessionIdAtom, id);
  Logger.debug("Regenerated session ID", { sessionId: id });
  return id;
}
