import type { StandaloneChatEvent } from "~/lib/api";
import { foldRunSteps } from "./fold-steps";
import { deriveLiveStateFromBlocks } from "./live-state";
import { text } from "./payload";
import type { RunBlock } from "./types";

/**
 * Infers the quiet gap after a tool finishes while the run is still active.
 * This drives a presence indicator only; it never fabricates thought text.
 * A streamed thinking block is real thought and renders itself, so the
 * indicator stays hidden while one is the trailing block.
 */
export function shouldShowAgentThinking(
  blocks: RunBlock[],
  running: boolean,
): boolean {
  if (!running) return false;
  const live = deriveLiveStateFromBlocks(blocks, null, "running");
  return live.state === "thinking" && blocks.at(-1)?.kind !== "thinking";
}

/**
 * Reconstructs the natural interleaving of an agent run: contiguous streamed
 * text becomes a markdown block, contiguous tool work becomes a step group.
 * A run that narrates between tool chains therefore renders as
 * [steps] → [text] → [steps] → [text] in stream order.
 */
export function foldRunBlocks(
  events: StandaloneChatEvent[],
  runId: string,
): RunBlock[] {
  const steps = foldRunSteps(events, runId);
  const stepsBySequence = new Map(steps.map((step) => [step.sequence, step]));
  const runEvents = events
    .filter((event) => event.run_id === runId)
    .sort((a, b) => a.sequence - b.sequence);
  const blocks: RunBlock[] = [];
  let textBuffer = "";
  let textKey = "";
  let thinkingBuffer = "";
  let thinkingKey = "";
  const flushText = () => {
    if (!textBuffer.trim()) {
      textBuffer = "";
      return;
    }
    blocks.push({ kind: "text", key: `text-${textKey}`, text: textBuffer });
    textBuffer = "";
  };
  const flushThinking = () => {
    if (!thinkingBuffer.trim()) {
      thinkingBuffer = "";
      return;
    }
    blocks.push({
      kind: "thinking",
      key: `thinking-${thinkingKey}`,
      text: thinkingBuffer,
    });
    thinkingBuffer = "";
  };
  for (const event of runEvents) {
    // Subagent-internal streams belong to their spawn card, never to the
    // run's own narration or thinking.
    if (
      (event.type === "text_delta" || event.type === "thinking_delta") &&
      text(event.payload.parent_tool_call_id)
    ) {
      continue;
    }
    if (event.type === "text_delta") {
      flushThinking();
      const delta = event.payload.delta;
      if (typeof delta === "string") {
        if (!textBuffer) textKey = `${event.run_id}-${event.sequence}`;
        textBuffer += delta;
      }
      continue;
    }
    if (event.type === "thinking_delta") {
      flushText();
      const delta = event.payload.delta;
      if (typeof delta === "string") {
        if (!thinkingBuffer) thinkingKey = `${event.run_id}-${event.sequence}`;
        thinkingBuffer += delta;
      }
      continue;
    }
    if (
      event.type === "status" &&
      event.payload.reset_text === true
    ) {
      // A retry restarted the answer: drop the streamed text so far.
      textBuffer = "";
      thinkingBuffer = "";
      for (let index = blocks.length - 1; index >= 0; index -= 1) {
        if (blocks[index].kind === "text" || blocks[index].kind === "thinking") {
          blocks.splice(index, 1);
        }
      }
      continue;
    }
    const step = stepsBySequence.get(event.sequence);
    if (!step) continue;
    flushThinking();
    flushText();
    const last = blocks[blocks.length - 1];
    if (last?.kind === "steps") {
      last.steps.push(step);
    } else {
      blocks.push({ kind: "steps", key: `steps-${step.key}`, steps: [step] });
    }
  }
  flushThinking();
  flushText();
  return blocks;
}
