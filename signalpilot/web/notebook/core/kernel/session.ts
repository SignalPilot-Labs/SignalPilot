import { init } from "@paralleldrive/cuid2";
import { Logger } from "@/utils/Logger";
import type { TypedString } from "@/utils/typed";
import { updateQueryParams } from "@/utils/urls";
import { KnownQueryParams } from "../constants";

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
  return /^s_[\da-z]{6}$/.test(value);
}

function getProjectDirFromStorage(): string | null {
  try {
    const raw = localStorage.getItem("sp:dbt-project-dir");
    if (raw && raw !== "null") {
      return JSON.parse(raw) as string | null;
    }
  } catch {
    // ignore
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

// Mutable session ID — can be updated for in-page notebook switching.
// During SSR (no window) we generate a placeholder ID; the client-side
// hydration will re-run the full URL-based logic via getSessionId().
let sessionId: SessionId = (() => {
  if (typeof window === "undefined") {
    return generateSessionId();
  }

  const url = new URL(window.location.href);
  const id = url.searchParams.get(
    KnownQueryParams.sessionId,
  ) as SessionId | null;
  if (isSessionId(id)) {
    updateQueryParams((params) => {
      if (params.has(KnownQueryParams.kiosk)) {
        return;
      }
      params.delete(KnownQueryParams.sessionId);
    });
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

  Logger.debug("Starting a new session", { sessionId: id });
  return generateSessionId();
})();

/**
 * Get the current session ID.
 */
export function getSessionId(): SessionId {
  return sessionId;
}

/**
 * Set the session ID to a specific value. Used by the embed boot
 * to reuse an existing pod session instead of creating a new one.
 */
export function setSessionId(id: SessionId): void {
  sessionId = id;
  Logger.debug("Set session ID", { sessionId });
}

/**
 * Generate a new session ID and update the module-level variable.
 * Used for in-page notebook switching.
 */
export function regenerateSessionId(): SessionId {
  sessionId = generateSessionId();
  Logger.debug("Regenerated session ID", { sessionId });
  return sessionId;
}
