"use client";

import { useState } from "react";
import { useOrganizationList } from "@clerk/nextjs";

export interface UseCreateTeamResult {
  loading: boolean;
  error: string | null;
  createTeam: (name: string) => Promise<void>;
}

/**
 * Shared hook wrapping Clerk's createOrganization + setActive.
 * Used by onboarding team-step and (stretch) sidebar create-team form.
 *
 * Fail fast: never swallows errors with a default name — surfaces them inline.
 */
export function useCreateTeam(): UseCreateTeamResult {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { createOrganization, setActive, isLoaded } = useOrganizationList();

  async function createTeam(name: string): Promise<void> {
    if (!isLoaded) {
      throw new Error("Clerk is not yet loaded");
    }
    if (!createOrganization || !setActive) {
      throw new Error("createOrganization is not available — ensure Organizations are enabled in Clerk dashboard");
    }

    setLoading(true);
    setError(null);

    try {
      const org = await createOrganization({ name });
      await setActive({ organization: org.id });
    } catch (e) {
      const message =
        e instanceof Error ? e.message : String(e);
      setError(message);
      throw e;
    } finally {
      setLoading(false);
    }
  }

  return { loading, error, createTeam };
}
