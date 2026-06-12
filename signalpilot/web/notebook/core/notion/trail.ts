import { KnownQueryParams } from "../constants";

export const NOTION_TRAIL_FILE_PREFIX = "signalpilot-notion-analyses/";
export const NOTION_TRAIL_SESSION_PREFIX = "session-notion-";

export function isNotionTrailParams({
  file,
  sessionId,
}: {
  file?: string | null;
  sessionId?: string | null;
}): boolean {
  return Boolean(
    sessionId?.startsWith(NOTION_TRAIL_SESSION_PREFIX) ||
      file?.startsWith(NOTION_TRAIL_FILE_PREFIX),
  );
}

export function isNotionTrailSearchParams(params: URLSearchParams): boolean {
  return isNotionTrailParams({
    file: params.get(KnownQueryParams.filePath),
    sessionId: params.get(KnownQueryParams.sessionId),
  });
}

export function notionRequestIdFromSessionId(
  sessionId: string | null | undefined,
): string | undefined {
  if (!sessionId?.startsWith(NOTION_TRAIL_SESSION_PREFIX)) {
    return undefined;
  }
  return `notion-${sessionId.slice(NOTION_TRAIL_SESSION_PREFIX.length)}`;
}

export function sanitizeNotionTrailSearchParams(
  params: URLSearchParams,
): URLSearchParams {
  const next = new URLSearchParams();
  const file = params.get(KnownQueryParams.filePath);
  const sessionId = params.get(KnownQueryParams.sessionId);

  if (file) {
    next.set(KnownQueryParams.filePath, file);
  }
  if (sessionId) {
    next.set(KnownQueryParams.sessionId, sessionId);
  }

  return next;
}

