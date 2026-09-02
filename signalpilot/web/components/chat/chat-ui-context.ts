"use client";

// Shared UI context for the standalone data chat message tree.
// Keep one context instance. All modules import it from this file.

import { createContext, useContext } from "react";
import type {
  ConversationFileInfo,
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
  /** The conversation the messages belong to; null on the empty new-chat page. */
  conversationId: string | null;
  /** The gateway's conversation file manifest (drives inline artifact cards). */
  files: ConversationFileInfo[];
  /** Open the artifacts panel focused on one file. */
  openArtifact: (fileId: string) => void;
  /**
   * Override for fetching a file's content as an object URL. The fixture
   * harness injects this (it has no gateway) so image thumbnails stay
   * verifiable at /chats/test; live pages omit it and the cards fall back
   * to the authenticated API helper.
   */
  getFileObjectUrl?: (fileId: string) => Promise<string>;
  /**
   * Frozen clock for relative timestamps (epoch ms). Injected by the
   * fixture harness so replayed frames show honest times; live pages omit
   * it and the cards tick on the real clock.
   */
  nowMs?: number;
  /** Opens the right-side Chat settings panel (connectors, budgets). */
  openChatSettings?: () => void;
  onStop: (runId: string) => Promise<void>;
  onRetry: (runId: string) => Promise<void>;
  onApproveReportSuggestion: (
    messageId: string,
  ) => Promise<{ report_id: string }>;
  onOpenDashboardPreview: (sessionId: string) => void;
};

export const ChatUiContext = createContext<ChatUiContextValue | null>(null);

export function useChatUi() {
  const value = useContext(ChatUiContext);
  if (!value) throw new Error("Standalone chat UI context is missing");
  return value;
}
