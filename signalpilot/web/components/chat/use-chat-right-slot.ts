"use client";

import { useCallback, useRef } from "react";
import type { StandaloneChatEvent, StandaloneChatRun } from "~/lib/api";
import type { UiMessage } from "~/components/chat/chat-ui-context";
import { useChatDashboardPanel } from "~/components/chat/use-chat-dashboard-panel";
import { useChatSettingsPanel } from "~/components/chat/use-chat-settings-panel";
import { useOpenArtifact } from "~/components/chat/use-open-artifact";

/**
 * The chat's right-hand slot shows ONE panel at a time: the artifacts panel,
 * the chat settings panel, or the dashboard preview. This hook wires the
 * three so opening one tucks the others away:
 *
 * - the dashboard closes artifacts and dismisses settings when it opens
 *   (a run's preview auto-opens it, so it must win);
 * - settings tucks away whichever sibling is showing and hands the slot back
 *   on close;
 * - opening artifacts (toggle or inline card) closes the dashboard for good
 *   and dismisses settings.
 *
 * The ref breaks the hook cycle between the dashboard and settings hooks.
 */
export function useChatRightSlot({
  conversationId,
  uiMessages,
  events,
  currentRun,
  artifactsOpen,
  setArtifactsOpen,
}: {
  conversationId: string | undefined;
  uiMessages: UiMessage[];
  events: StandaloneChatEvent[];
  currentRun: StandaloneChatRun | null;
  artifactsOpen: boolean;
  setArtifactsOpen: (open: boolean) => void;
}) {
  const closeSiblingsRef = useRef<() => void>(() => undefined);
  const closeSiblings = useCallback(() => closeSiblingsRef.current(), []);
  const dashboard = useChatDashboardPanel({
    conversationId,
    uiMessages,
    events,
    currentRun,
    onOpen: closeSiblings,
  });
  const settings = useChatSettingsPanel(artifactsOpen, setArtifactsOpen, {
    open: Boolean(dashboard.sessionId),
    dismiss: dashboard.dismiss,
    reopen: dashboard.reopen,
  });
  closeSiblingsRef.current = () => {
    setArtifactsOpen(false);
    settings.dismiss();
  };
  const { close: closeDashboard } = dashboard;
  const { dismiss: dismissSettings } = settings;
  const openArtifacts = useCallback(() => {
    closeDashboard();
    dismissSettings();
    setArtifactsOpen(true);
  }, [closeDashboard, dismissSettings, setArtifactsOpen]);
  // Inline artifact cards open the panel focused on their file.
  const { openFileRequest, openArtifact } = useOpenArtifact(openArtifacts);

  return { dashboard, settings, openArtifacts, openFileRequest, openArtifact };
}
