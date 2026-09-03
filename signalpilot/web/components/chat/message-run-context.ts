"use client";

// Per-message run context for the standalone data chat.
//
// An unresolved inline file reference is "pending" only while the run
// that produced its message is still streaming. A later run must not flip
// an older message's missing reference back to a loading state, so the
// running flag lives here, per message, not on the shared chat context.

import { createContext, useContext } from "react";

export type MessageRunContextValue = {
  /** The run that produced the message, or null when unknown. */
  runId: string | null;
  /** True while that run is queued or running. */
  running: boolean;
};

const NOT_RUNNING: MessageRunContextValue = { runId: null, running: false };

export const MessageRunContext = createContext<MessageRunContextValue | null>(
  null,
);

/** Soft read: outside a message (playground, file viewer) nothing is running. */
export function useMessageRun(): MessageRunContextValue {
  return useContext(MessageRunContext) ?? NOT_RUNNING;
}
