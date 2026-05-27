"use client";

import { useCallback } from "react";
import { useUser } from "@clerk/nextjs";

export interface OnboardingStatus {
  /** null = still loading */
  isComplete: boolean | null;
  markComplete: () => Promise<void>;
  isLoading: boolean;
}

export function useOnboardingStatus(): OnboardingStatus {
  const { isLoaded, user } = useUser();

  const isLoading = !isLoaded;
  const isComplete = isLoaded
    ? user?.unsafeMetadata?.onboardingCompleted === true
    : null;

  const markComplete = useCallback(async (): Promise<void> => {
    if (!user) throw new Error("No authenticated user");
    await user.update({
      unsafeMetadata: {
        ...user.unsafeMetadata,
        onboardingCompleted: true,
      },
    });
  }, [user]);

  return { isComplete: isComplete ?? null, markComplete, isLoading };
}
