"use client";

import { useCallback } from "react";
import { useChatSettingsPanel } from "~/components/chat/use-chat-settings-panel";
import { useOpenArtifact } from "~/components/chat/use-open-artifact";

/**
 * The chat's right-hand slot shows ONE panel at a time: the artifacts panel
 * or the chat settings panel. This hook wires the two so opening one tucks
 * the other away:
 *
 * - settings tucks the artifacts panel away and hands the slot back on
 *   close;
 * - opening artifacts (toggle or inline card) dismisses settings.
 */
export function useChatRightSlot({
  artifactsOpen,
  setArtifactsOpen,
}: {
  artifactsOpen: boolean;
  setArtifactsOpen: (open: boolean) => void;
}) {
  const settings = useChatSettingsPanel(artifactsOpen, setArtifactsOpen);
  const { dismiss: dismissSettings } = settings;
  const openArtifacts = useCallback(() => {
    dismissSettings();
    setArtifactsOpen(true);
  }, [dismissSettings, setArtifactsOpen]);
  // Inline artifact cards open the panel focused on their file.
  const { openFileRequest, openArtifact } = useOpenArtifact(openArtifacts);

  return { settings, openArtifacts, openFileRequest, openArtifact };
}
