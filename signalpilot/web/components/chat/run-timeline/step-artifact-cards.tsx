"use client";

// Artifact cards anchored to the timeline step that produced the file.
//
// The message derives one card per file (lib/chat-artifact-cards.ts) and
// groups them by the producing step's sequence. This context carries that
// map down the timeline so each step row can render its cards right below
// itself, and a collapsed group can hoist its cards into a visible footer.

import { createContext, useContext } from "react";
import type { RunStep } from "~/lib/chat-run-steps";
import type { ArtifactCardModel } from "~/lib/chat-artifact-cards";
import { ChatArtifactCards } from "~/components/chat/chat-artifact-card";
import { ChatUiContext } from "~/components/chat/chat-ui-context";

export const StepArtifactCardsContext = createContext<Map<
  number,
  ArtifactCardModel[]
> | null>(null);

/** Cards for every step of a group, in step order, children included. */
export function collectGroupArtifactCards(
  steps: RunStep[],
  byStep: Map<number, ArtifactCardModel[]> | null,
): ArtifactCardModel[] {
  if (!byStep || byStep.size === 0) return [];
  const cards: ArtifactCardModel[] = [];
  const walk = (list: RunStep[]) => {
    for (const step of list) {
      const own = byStep.get(step.sequence);
      if (own) cards.push(...own);
      if (step.children.length) walk(step.children);
    }
  };
  walk(steps);
  return cards;
}

/** Sequences of every rendered step, children included. */
export function collectStepSequences(steps: RunStep[]): Set<number> {
  const sequences = new Set<number>();
  const walk = (list: RunStep[]) => {
    for (const step of list) {
      sequences.add(step.sequence);
      if (step.children.length) walk(step.children);
    }
  };
  walk(steps);
  return sequences;
}

/** The card block for one group of cards; works without a chat context. */
export function ArtifactCardBlock({
  cards,
  testId,
  anchorSequence,
  className,
}: {
  cards: ArtifactCardModel[];
  testId: string;
  anchorSequence?: number;
  className?: string;
}) {
  const ui = useContext(ChatUiContext);
  if (cards.length === 0) return null;
  return (
    <div
      data-testid={testId}
      data-anchor-sequence={anchorSequence}
      className={className}
      aria-live="polite"
    >
      <ChatArtifactCards
        cards={cards}
        conversationId={ui?.conversationId ?? null}
        onOpen={ui?.openArtifact ?? (() => undefined)}
      />
    </div>
  );
}

/**
 * The cards produced by one step, rendered as a timeline row directly
 * below that step. Renders nothing when the step produced no file.
 */
export function StepArtifactCards({ sequence }: { sequence: number }) {
  const byStep = useContext(StepArtifactCardsContext);
  const cards = byStep?.get(sequence);
  if (!cards || cards.length === 0) return null;
  return (
    <li className="chat-step-in relative list-none pl-7">
      <ArtifactCardBlock
        cards={cards}
        testId="chat-step-artifact-cards"
        anchorSequence={sequence}
        className="pb-1"
      />
    </li>
  );
}
