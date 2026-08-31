"use client";

// Shared UI context for the standalone data chat message tree.
// Keep one context instance. All modules import it from this file.

import { createContext, useContext } from "react";
import type {
  StandaloneChatArtifact,
  StandaloneChatEvent,
  StandaloneChatMessage,
  StandaloneChatRunStatus,
} from "~/lib/api";
import type { StandaloneRunActivity } from "~/lib/standalone-chat-state";

export type UiMessage = StandaloneChatMessage & {
  runId?: string;
  runStatus?: StandaloneChatRunStatus;
  activity?: StandaloneRunActivity;
  synthetic?: boolean;
};

export type ChatUiContextValue = {
  events: StandaloneChatEvent[];
  artifacts: StandaloneChatArtifact[];
  onStop: (runId: string) => Promise<void>;
  onRetry: (runId: string) => Promise<void>;
  onApproveReportSuggestion: (
    messageId: string,
  ) => Promise<{ report_id: string }>;
};

export const ChatUiContext = createContext<ChatUiContextValue | null>(null);

export function useChatUi() {
  const value = useContext(ChatUiContext);
  if (!value) throw new Error("Standalone chat UI context is missing");
  return value;
}
