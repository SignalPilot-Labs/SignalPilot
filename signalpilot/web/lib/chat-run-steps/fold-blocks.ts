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
 * Where each follow-up sent during the run belongs: the sequence of its
 * `steering_delivered` event (the moment the model read it, exact). A
 * finished run recorded before that event existed falls back to its
 * `steering_picked_up` event (when it was handed to the agent); a live run
 * never does, so a message cannot jump from one anchor to the other. A
 * message with no anchor yet renders at the bottom of the run.
 */
const TERMINAL_STATUSES = new Set(["completed", "failed", "cancelled"]);

export function steeringAnchors(
  events: StandaloneChatEvent[],
  runId: string,
): Map<number, string[]> {
  const delivered = new Map<string, number>();
  const pickedUp = new Map<string, number>();
  let finished = false;
  for (const event of events) {
    if (event.run_id !== runId) continue;
    if (event.type === "status" && TERMINAL_STATUSES.has(String(event.payload.status))) {
      finished = true;
    }
    const messageId = text(event.payload.message_id);
    if (!messageId) continue;
    if (event.type === "steering_delivered" && !delivered.has(messageId)) {
      delivered.set(messageId, event.sequence);
    } else if (event.type === "steering_picked_up" && !pickedUp.has(messageId)) {
      pickedUp.set(messageId, event.sequence);
    }
  }
  const anchors = new Map<number, string[]>();
  const ids = finished ? new Set([...delivered.keys(), ...pickedUp.keys()]) : delivered.keys();
  for (const messageId of ids) {
    const sequence = delivered.get(messageId) ?? pickedUp.get(messageId)!;
    anchors.set(sequence, [...(anchors.get(sequence) ?? []), messageId]);
  }
  return anchors;
}

/**
 * Reconstructs the natural interleaving of an agent run: contiguous streamed
 * text becomes a markdown block, contiguous tool work becomes a step group.
 * A run that narrates between tool chains therefore renders as
 * [steps] → [text] → [steps] → [text] in stream order. A follow-up the user
 * sent mid-run becomes an interjection block at the point the agent read it,
 * so the work that answers it flows below it.
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
  const anchors = steeringAnchors(runEvents, runId);
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
    const interjections = anchors.get(event.sequence);
    if (interjections) {
      flushThinking();
      flushText();
      for (const messageId of interjections) {
        blocks.push({ kind: "interjection", key: `interjection-${messageId}`, messageId });
      }
      continue;
    }
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
