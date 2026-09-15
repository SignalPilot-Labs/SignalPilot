"use client";

// The org-wide default chat project: what the bootstrap resolved, and the
// admin-only setter. Picking a project for one conversation never touches
// it; only the explicit "set as org default" control does.

import { useCallback, useEffect, useState } from "react";
import {
  setDefaultStandaloneChatProject,
  type StandaloneChatBootstrap,
} from "~/lib/api";
import { useToast } from "~/components/ui/toast";

export function useDefaultChatProject(
  bootstrap: StandaloneChatBootstrap | undefined,
): {
  defaultProjectId: string | null;
  setDefaultProject: (projectId: string) => Promise<void>;
} {
  const { toast } = useToast();
  const resolved = bootstrap?.selected_project_id ?? null;
  const [defaultProjectId, setDefaultProjectId] = useState<string | null>(resolved);

  useEffect(() => {
    setDefaultProjectId(resolved);
  }, [resolved]);

  const setDefaultProject = useCallback(
    async (projectId: string) => {
      try {
        await setDefaultStandaloneChatProject(projectId);
        setDefaultProjectId(projectId);
        toast("Default chat project updated for your org", "success");
      } catch (error) {
        toast(
          error instanceof Error ? error.message : "Could not set the default project",
          "error",
        );
      }
    },
    [toast],
  );

  return { defaultProjectId, setDefaultProject };
}
