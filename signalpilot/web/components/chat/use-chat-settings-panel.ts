"use client";

import { useCallback, useRef, useState } from "react";

/**
 * Open/close state for the Chat settings panel. It shares the right-hand
 * slot with the artifacts panel: opening settings tucks the artifacts panel
 * away and closing settings brings it back if it was open.
 */
export function useChatSettingsPanel(
  artifactsOpen: boolean,
  setArtifactsOpen: (open: boolean) => void,
) {
  const [open, setOpen] = useState(false);
  const artifactsWereOpen = useRef(false);

  const openPanel = useCallback(() => {
    artifactsWereOpen.current = artifactsOpen;
    if (artifactsOpen) setArtifactsOpen(false);
    setOpen(true);
  }, [artifactsOpen, setArtifactsOpen]);

  const closePanel = useCallback(() => {
    setOpen(false);
    if (artifactsWereOpen.current) setArtifactsOpen(true);
    artifactsWereOpen.current = false;
  }, [setArtifactsOpen]);

  const toggle = useCallback(() => {
    if (open) closePanel();
    else openPanel();
  }, [closePanel, open, openPanel]);

  return { open, openPanel, closePanel, toggle };
}
