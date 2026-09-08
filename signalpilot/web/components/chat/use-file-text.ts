"use client";

import { useContext, useEffect, useState } from "react";
import { getConversationFileText, type ConversationFileInfo } from "~/lib/api";
import { ChatUiContext } from "~/components/chat/chat-ui-context";

export type FileTextState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "text"; text: string };

/** One fetch key per file version: a new content hash reads as a reload. */
function versionKey(conversationId: string, file: ConversationFileInfo): string {
  return `${conversationId}:${file.id}:${file.content_hash}`;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Could not load the file";
}

/**
 * Text of several file versions at once. Honors the ChatUiContext
 * `getFileText` override (the shared page reads through its share-token
 * route; the fixture harness serves literal contents); owner pages fetch
 * through the conversation route. Results are keyed by file id; a file
 * whose version changed reads as loading again until its new text lands.
 */
export function useFileTexts(
  conversationId: string,
  files: readonly ConversationFileInfo[],
): Record<string, FileTextState> {
  const override = useContext(ChatUiContext)?.getFileText;
  const [loaded, setLoaded] = useState<Record<string, FileTextState>>({});
  // A stable string so the effect re-runs only when the set of versions
  // changes, not on every new array identity.
  const wanted = files.map((file) => versionKey(conversationId, file)).join("\n");
  useEffect(() => {
    let cancelled = false;
    const keys = wanted ? wanted.split("\n") : [];
    for (const file of files) {
      const key = versionKey(conversationId, file);
      if (!keys.includes(key) || key in loaded) continue;
      (override ? override(file.id) : getConversationFileText(conversationId, file.id))
        .then((text) => {
          if (!cancelled) setLoaded((prev) => ({ ...prev, [key]: { phase: "text", text } }));
        })
        .catch((error: unknown) => {
          if (cancelled) return;
          setLoaded((prev) => ({
            ...prev,
            [key]: { phase: "error", message: errorMessage(error) },
          }));
        });
    }
    return () => {
      cancelled = true;
    };
    // `files` is covered by `wanted`; `loaded` is read, not a trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId, wanted, override]);
  const out: Record<string, FileTextState> = {};
  for (const file of files) {
    out[file.id] = loaded[versionKey(conversationId, file)] ?? { phase: "loading" };
  }
  return out;
}

/** Text of one file version (see `useFileTexts`). */
export function useFileText(
  conversationId: string,
  file: ConversationFileInfo,
): FileTextState {
  // Array identity does not matter: the fetch effect keys on the version.
  return useFileTexts(conversationId, [file])[file.id] ?? { phase: "loading" };
}
