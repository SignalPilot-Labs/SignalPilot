"use client";

// Shared UI context for the standalone data chat message tree.
// Keep one context instance. All modules import it from this file.

import { createContext, useContext } from "react";
import type {
  ConversationFileInfo,
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
  /** The conversation the messages belong to; null on the empty new-chat page. */
  conversationId: string | null;
  /** The gateway's conversation file manifest (drives inline artifact cards). */
  files: ConversationFileInfo[];
  /**
   * The run currently streaming, or null. An inline file reference that
   * does not resolve yet renders as pending while this is set and as
   * missing once it is null.
   */
  runningRunId: string | null;
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
   * Override for downloading a file's bytes. The shared read-only page
   * injects it (its files live behind the share-token routes); owner pages
   * omit it and the inline figure and chip download through the
   * conversation route.
   */
  downloadFile?: (fileId: string, filename: string) => Promise<void>;
  /**
   * Override for paging the full rows of a governed query result. The
   * fixture harness injects a deterministic generator; live pages omit it
   * and the table card falls back to the authenticated API helper.
   */
  getToolResultRows?: (
    resultId: string,
    opts?: { offset?: number; limit?: number },
  ) => Promise<{
    columns: { name: string; logical_type?: string | null }[];
    rows: unknown[][];
    saved_row_count: number;
  }>;
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
  onOpenDashboardPreview: (sessionId: string) => void;
};

export const ChatUiContext = createContext<ChatUiContextValue | null>(null);

export function useChatUi() {
  const value = useContext(ChatUiContext);
  if (!value) throw new Error("Standalone chat UI context is missing");
  return value;
}
