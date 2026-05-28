import { useEffect } from "react";
import type { components } from "@/packages/sp-api";
import { spApiUrl } from "@/core/network/api";

export type FsEvent = components["schemas"]["FsEvent"];

/**
 * Subscribe to file-system change events from the server via SSE.
 *
 * The hook is stateless — no debouncing. Call sites are responsible for
 * wrapping `onChange` in a debounce when needed (e.g. 250 ms via
 * `useDebouncedCallback`).
 *
 * No-ops (no EventSource constructed) when the runtime URL is unavailable.
 * The server returns 204 in single-file mode, which causes EventSource to
 * fire `onerror` and stop — no retry storm.
 */
export function useFilesystemEvents(
  onChange: (events: FsEvent[]) => void,
): void {
  useEffect(() => {
    let sseUrl: string;
    try {
      sseUrl = spApiUrl("/files/events");
    } catch {
      return;
    }

    const es = new EventSource(sseUrl, { withCredentials: true });

    es.addEventListener("changes", (e: MessageEvent) => {
      const payload = JSON.parse(e.data) as { events: FsEvent[] };
      onChange(payload.events);
    });

    return () => {
      es.close();
    };
  }, [onChange]);
}
