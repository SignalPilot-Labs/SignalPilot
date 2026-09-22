"use client";

import { useCallback, useRef, useState } from "react";

/**
 * Open/close state for the Chat settings panel. It shares the right-hand
 * slot with the artifacts panel: opening settings tucks the artifacts panel
 * away, and closing settings brings it back. `dismiss` closes without
 * restoring, for when the artifacts panel takes the slot on its own.
 */
export function useChatSettingsPanel(
  artifactsOpen: boolean,
  setArtifactsOpen: (open: boolean) => void,
) {
  const [open, setOpen] = useState(false);
  const restore = useRef<"artifacts" | null>(null);

  const openPanel = useCallback(() => {
    restore.current = artifactsOpen ? "artifacts" : null;
    if (artifactsOpen) setArtifactsOpen(false);
    setOpen(true);
  }, [artifactsOpen, setArtifactsOpen]);

  const dismiss = useCallback(() => {
    setOpen(false);
    restore.current = null;
  }, []);

  const closePanel = useCallback(() => {
    setOpen(false);
    if (restore.current === "artifacts") setArtifactsOpen(true);
    restore.current = null;
  }, [setArtifactsOpen]);

  const toggle = useCallback(() => {
    if (open) closePanel();
    else openPanel();
  }, [closePanel, open, openPanel]);

  return { open, openPanel, closePanel, dismiss, toggle };
}
