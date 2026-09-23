"use client";

import { useCallback, useState } from "react";

/** Request handed to the ArtifactsPanel: open the Files tab on one file, or
 * the Notebook tab. The nonce re-applies the request even when the same
 * target is asked twice. */
export type ArtifactOpenRequest =
  | { kind: "file"; fileId: string; nonce: number }
  | { kind: "notebook"; nonce: number };

/**
 * Shared wiring between an inline artifact card (or an artifact notice)
 * and the artifacts panel. `openPanel` makes the panel visible; the
 * returned request tells it what to focus. Used by the chat page and the
 * fixture harness alike.
 */
export function useOpenArtifact(openPanel: () => void): {
  openFileRequest: ArtifactOpenRequest | null;
  openArtifact: (fileId: string) => void;
  openNotebook: () => void;
} {
  const [openFileRequest, setOpenFileRequest] =
    useState<ArtifactOpenRequest | null>(null);
  const openArtifact = useCallback(
    (fileId: string) => {
      openPanel();
      setOpenFileRequest((previous) => ({
        kind: "file",
        fileId,
        nonce: (previous?.nonce ?? 0) + 1,
      }));
    },
    [openPanel],
  );
  const openNotebook = useCallback(() => {
    openPanel();
    setOpenFileRequest((previous) => ({
      kind: "notebook",
      nonce: (previous?.nonce ?? 0) + 1,
    }));
  }, [openPanel]);
  return { openFileRequest, openArtifact, openNotebook };
}
