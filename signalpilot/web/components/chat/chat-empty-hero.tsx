"use client";

import { Sparkles } from "lucide-react";
import type { ReactNode } from "react";

/** The empty new-chat hero: headline, blurb, and the composer as focal point. */
export function ChatEmptyHero({ composer }: { composer: ReactNode }) {
  return (
    <div className="mb-6 text-center">
      <div className="mx-auto mb-5 flex h-11 w-11 items-center justify-center rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-card)]">
        <Sparkles className="h-5 w-5 text-[var(--color-success)]" />
      </div>
      <h1 className="text-[32px] font-semibold leading-tight tracking-[-0.025em] text-[var(--color-text)]">
        What would you like to understand?
      </h1>
      <p className="mx-auto mt-3 max-w-xl text-[15px] leading-7 text-[var(--color-text-muted)]">
        Ask in plain English. SignalPilot will inspect the project, query
        governed production data, and choose the clearest answer format.
      </p>
      {/* The input is the focal point in the empty state. */}
      {composer}
    </div>
  );
}
