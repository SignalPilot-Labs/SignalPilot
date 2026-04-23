"use client";

import { type ReactNode } from "react";

export interface StepTransitionProps {
  /**
   * Accepted for API compatibility but not used internally.
   * The animation plays on every mount — which is already driven by
   * SignIn.Step / SignUp.Step unmounting and remounting on step change.
   * Passing key={stepKey} on the *caller* side would force remounting;
   * the inner `key` prop on a div has no effect.
   */
  stepKey: string;
  children: ReactNode;
}

/**
 * Tiny animation wrapper that applies animate-slide-in-right on mount.
 * Animation replay is driven by SignIn.Step / SignUp.Step mount/unmount —
 * each step renders only when active, so this wrapper naturally remounts.
 * No exit animation — deferred to round 4.
 *
 * Usage:
 *   <StepTransition stepKey="start">
 *     <SignIn.Step name="start">...</SignIn.Step>
 *   </StepTransition>
 */
export function StepTransition({ children }: StepTransitionProps) {
  return (
    <div className="animate-slide-in-right">
      {children}
    </div>
  );
}
