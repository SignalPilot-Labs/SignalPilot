"use client";

import { type ReactNode } from "react";

export interface StepTransitionProps {
  /**
   * Used to select the enter-animation axis:
   * - "verifications" → animate-slide-in-up (OTP step rises from below)
   * - anything else  → animate-slide-in-right
   *
   * Remount triggering is handled by Clerk Elements (SignIn.Step / SignUp.Step
   * unmounts when its step is inactive), so we don't need key-on-div tricks.
   */
  stepKey: string;
  children: ReactNode;
}

/**
 * Thin animation wrapper for Clerk Elements multi-step flows.
 * Picks enter-animation class from stepKey on mount.
 * Animation replays on every mount — already driven by Clerk's
 * Step remount cycle. No exit animation (exit owned by Clerk remount).
 */
export function StepTransition({ stepKey, children }: StepTransitionProps) {
  const animClass =
    stepKey === "verifications" ? "animate-slide-in-up" : "animate-slide-in-right";

  return (
    <div className={animClass}>
      {children}
    </div>
  );
}
