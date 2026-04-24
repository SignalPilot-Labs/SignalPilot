"use client";

/**
 * TeamStep — rendered during onboarding when a signed-in user has no active org.
 * Must complete before the existing API key wizard renders.
 *
 * Uses useCreateTeam() which wraps createOrganization + setActive.
 * Fail fast: errors are shown inline; no silent default team name.
 */

import { useState } from "react";
import { Users } from "lucide-react";
import { useCreateTeam } from "@/lib/use-create-team";
import { PendingButton } from "@/components/ui/pending-button";

interface TeamStepProps {
  /** Called after org is created + set active — parent advances to api-key wizard */
  onTeamCreated: () => void;
}

export function TeamStep({ onTeamCreated }: TeamStepProps) {
  const [teamName, setTeamName] = useState("");
  const { loading, error, createTeam } = useCreateTeam();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = teamName.trim();
    if (!trimmed) return;

    try {
      await createTeam(trimmed);
      onTeamCreated();
    } catch {
      // error is already set in useCreateTeam state — displayed inline below
    }
  }

  return (
    <div className="animate-fade-in">
      <div className="mb-6">
        <div className="flex items-center gap-2 mb-3">
          <Users
            className="w-4 h-4 text-[var(--color-text-dim)]"
            strokeWidth={1.5}
          />
          <h2 className="text-lg font-light text-[var(--color-text)] tracking-wider">
            name your team
          </h2>
        </div>
        <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider leading-relaxed">
          you can invite people later. solo? use your name or make something up.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label
            htmlFor="team-name"
            className="block text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.15em] mb-1.5"
          >
            team name
          </label>
          <input
            id="team-name"
            type="text"
            value={teamName}
            onChange={(e) => setTeamName(e.target.value)}
            placeholder="e.g. acme corp, solo ops, my workspace"
            autoFocus
            disabled={loading}
            className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-[13px] text-[var(--color-text)] font-mono tracking-wide focus:outline-none focus:border-[var(--color-border-hover)] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-text)] focus-visible:border-[var(--color-text)] disabled:opacity-50"
          />
        </div>

        {error && (
          <p
            role="alert"
            className="text-[12px] text-[var(--color-error)] tracking-wider"
          >
            {error}
          </p>
        )}

        <PendingButton
          type="submit"
          pending={loading}
          pendingLabel="creating team…"
          disabled={loading || !teamName.trim()}
        >
          create team
        </PendingButton>
      </form>
    </div>
  );
}
