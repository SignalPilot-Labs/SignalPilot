"use client";

import { useCallback, useRef, useState } from "react";

/** A sibling panel the settings panel can tuck away and hand the slot back. */
export type ChatSlotSibling = {
  open: boolean;
  /** Hide without changing the URL or forgetting what was shown. */
  dismiss: () => void;
  /** Show again what was hidden by `dismiss`. */
  reopen: () => void;
};

/**
 * Open/close state for the Chat settings panel. It shares the right-hand
 * slot with the artifacts panel and the dashboard preview panel: opening
 * settings tucks whichever sibling is showing away, and closing settings
 * brings that sibling back. `dismiss` closes without restoring, for when a
 * sibling takes the slot on its own.
 */
export function useChatSettingsPanel(
  artifactsOpen: boolean,
  setArtifactsOpen: (open: boolean) => void,
  dashboard?: ChatSlotSibling,
) {
  const [open, setOpen] = useState(false);
  const restore = useRef<"artifacts" | "dashboard" | null>(null);
  const dashboardOpen = dashboard?.open ?? false;
  const dashboardDismiss = dashboard?.dismiss;
  const dashboardReopen = dashboard?.reopen;

  const openPanel = useCallback(() => {
    restore.current = dashboardOpen
      ? "dashboard"
      : artifactsOpen
        ? "artifacts"
        : null;
    if (dashboardOpen) dashboardDismiss?.();
    if (artifactsOpen) setArtifactsOpen(false);
    setOpen(true);
  }, [artifactsOpen, dashboardDismiss, dashboardOpen, setArtifactsOpen]);

  const dismiss = useCallback(() => {
    setOpen(false);
    restore.current = null;
  }, []);

  const closePanel = useCallback(() => {
    setOpen(false);
    if (restore.current === "dashboard") dashboardReopen?.();
    else if (restore.current === "artifacts") setArtifactsOpen(true);
    restore.current = null;
  }, [dashboardReopen, setArtifactsOpen]);

  const toggle = useCallback(() => {
    if (open) closePanel();
    else openPanel();
  }, [closePanel, open, openPanel]);

  return { open, openPanel, closePanel, dismiss, toggle };
}
