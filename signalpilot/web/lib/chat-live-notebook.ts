import type { StandaloneChatEvent } from "~/lib/api";

/**
 * Where the chat agent's analysis notebook lives right now, derived from the
 * run event stream.
 *
 * The gateway emits `notebook_started` with the ids the live view needs:
 * - gateway_session_id: the sandbox session behind /notebook/{id}/ proxy paths
 * - kernel_session_id:  the kernel session (s_xxxxxx) inside that sandbox
 * - notebook_path:      absolute path of analysis.py inside the sandbox
 *
 * `kernel_stopped` (and run failure) flips the link to non-live; the archived
 * HTML notebook — announced by `archive_completed` / the run's
 * runtime_archive_available flag — is the fallback view after that.
 */
export type LiveNotebookLink = {
  runId: string;
  gatewaySessionId: string;
  kernelSessionId: string;
  notebookPath: string;
  /** True while the kernel session behind the link is expected to be alive. */
  live: boolean;
};

function payloadString(
  payload: Record<string, unknown>,
  key: string,
): string {
  const value = payload[key];
  return typeof value === "string" ? value : "";
}

/**
 * Fold a run's events into the latest attachable notebook link, or null when
 * the run never started a notebook (or never reported one we can attach to —
 * events from older gateways carry a bare `{status}` payload).
 */
export function deriveLiveNotebookLink(
  events: StandaloneChatEvent[],
  runId: string | undefined,
): LiveNotebookLink | null {
  if (!runId) return null;
  let link: LiveNotebookLink | null = null;
  for (const event of events
    .filter((candidate) => candidate.run_id === runId)
    .sort((left, right) => left.sequence - right.sequence)) {
    if (event.type === "notebook_started") {
      const gatewaySessionId = payloadString(event.payload, "gateway_session_id");
      const kernelSessionId = payloadString(event.payload, "kernel_session_id");
      const notebookPath = payloadString(event.payload, "notebook_path");
      if (gatewaySessionId && kernelSessionId && notebookPath) {
        link = {
          runId,
          gatewaySessionId,
          kernelSessionId,
          notebookPath,
          live: true,
        };
      }
    } else if (event.type === "kernel_stopped" && link !== null) {
      const stopped: LiveNotebookLink = { ...link, live: false };
      link = stopped;
    }
  }
  return link;
}

/** URL of the full-page /chat-notebook pop-out for a live link. */
export function buildChatNotebookPopoutUrl(link: LiveNotebookLink): string {
  const params = new URLSearchParams({
    gw_session: link.gatewaySessionId,
    session_id: link.kernelSessionId,
    file: link.notebookPath,
    run_id: link.runId,
  });
  return `/chat-notebook?${params.toString()}`;
}
