"use client";

import { useCallback, useState } from "react";

/** Request handed to the ArtifactsPanel: open the Files tab on one file.
 * The nonce re-applies the request even when the same file is asked twice. */
export type ArtifactOpenRequest = { fileId: string; nonce: number };

/**
 * Shared wiring between an inline artifact card and the artifacts panel.
 * `openPanel` makes the panel visible; the returned request tells it which
 * file to focus. Used by the chat page and the fixture harness alike.
 */
export function useOpenArtifact(openPanel: () => void): {
  openFileRequest: ArtifactOpenRequest | null;
  openArtifact: (fileId: string) => void;
} {
  const [openFileRequest, setOpenFileRequest] =
    useState<ArtifactOpenRequest | null>(null);
  const openArtifact = useCallback(
    (fileId: string) => {
      openPanel();
      setOpenFileRequest((previous) => ({
        fileId,
        nonce: (previous?.nonce ?? 0) + 1,
      }));
    },
    [openPanel],
  );
  return { openFileRequest, openArtifact };
}
