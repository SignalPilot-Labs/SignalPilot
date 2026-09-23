"use client";

// Render-stability helpers for the chat transcript.
//
// A streamed run event replaces the whole `events` array, and a 1 s poll
// replaces every object in the conversation detail with fresh JSON. Without
// these helpers every message, and every step row inside it, re-renders on
// each event even when its own run did not change. The helpers keep the
// previous object when the new one is equal, so React.memo and context
// consumers skip the work.

import { useMemo, useRef } from "react";
import type { StandaloneChatEvent } from "~/lib/api";
import type {
  ChatUiContextValue,
  UiMessage,
} from "~/components/chat/chat-ui-context";

const NO_EVENTS: StandaloneChatEvent[] = [];

function shallowEqualObjects(left: object, right: object): boolean {
  if (left === right) return true;
  const leftRecord = left as Record<string, unknown>;
  const rightRecord = right as Record<string, unknown>;
  const leftKeys = Object.keys(leftRecord);
  if (leftKeys.length !== Object.keys(rightRecord).length) return false;
  return leftKeys.every(
    (key) =>
      Object.prototype.hasOwnProperty.call(rightRecord, key) &&
      Object.is(leftRecord[key], rightRecord[key]),
  );
}

function sameJson(left: unknown, right: unknown): boolean {
  if (left === right) return true;
  try {
    return JSON.stringify(left) === JSON.stringify(right);
  } catch {
    return false;
  }
}

// Serialized payloads, cached per event object: a poll compares each fresh
// copy against the cached text of the event it replaces.
const payloadText = new WeakMap<StandaloneChatEvent, string | null>();

function eventPayloadText(event: StandaloneChatEvent): string | null {
  let text = payloadText.get(event);
  if (text === undefined) {
    try {
      text = JSON.stringify(event.payload);
    } catch {
      text = null;
    }
    payloadText.set(event, text);
  }
  return text;
}

function sameEvent(
  left: StandaloneChatEvent,
  right: StandaloneChatEvent,
): boolean {
  if (left === right) return true;
  if (
    left.run_id !== right.run_id ||
    left.sequence !== right.sequence ||
    left.type !== right.type ||
    left.created_at !== right.created_at
  ) {
    return false;
  }
  const leftText = eventPayloadText(left);
  return leftText !== null && leftText === eventPayloadText(right);
}

/** True when both lists hold the same events in the same order. */
export function sameEventList(
  left: StandaloneChatEvent[],
  right: StandaloneChatEvent[],
): boolean {
  if (left === right) return true;
  if (left.length !== right.length) return false;
  for (let index = 0; index < left.length; index += 1) {
    if (!sameEvent(left[index]!, right[index]!)) return false;
  }
  return true;
}

/** Keep the previous value while `equal` says the new one is the same. */
function useStableValue<T>(value: T, equal: (left: T, right: T) => boolean): T {
  const ref = useRef(value);
  if (ref.current !== value && !equal(ref.current, value)) {
    ref.current = value;
  }
  return ref.current;
}

/**
 * The ChatUiContext value with a stable identity. The page re-renders on
 * every keystroke and event; a fresh object literal would re-render every
 * context consumer in the transcript each time.
 */
export function useChatUiValue(value: ChatUiContextValue): ChatUiContextValue {
  return useStableValue(value, shallowEqualObjects);
}

// Events grouped by run, built once per events array and shared by every
// message on the page.
const runIndexCache = new WeakMap<
  StandaloneChatEvent[],
  Map<string, StandaloneChatEvent[]>
>();

function eventsForRun(
  events: StandaloneChatEvent[],
  runId: string,
): StandaloneChatEvent[] {
  if (!runId) return NO_EVENTS;
  let index = runIndexCache.get(events);
  if (!index) {
    index = new Map();
    for (const event of events) {
      const list = index.get(event.run_id);
      if (list) list.push(event);
      else index.set(event.run_id, [event]);
    }
    runIndexCache.set(events, index);
  }
  return index.get(runId) ?? NO_EVENTS;
}

/**
 * One run's events, in order, with an identity that changes only when that
 * run's events change. Events of other runs, and fresh JSON copies of the
 * same events from a poll, do not change it.
 */
export function useRunEvents(
  events: StandaloneChatEvent[],
  runId: string,
): StandaloneChatEvent[] {
  const runEvents = useMemo(() => eventsForRun(events, runId), [events, runId]);
  return useStableValue(runEvents, sameEventList);
}

/**
 * The chat UI context scoped to one message's run: `events` holds only that
 * run's events. Every consumer inside a message reads events for its own
 * run, so the scoped value stays the same while other runs stream.
 */
export function useRunScopedChatUi(
  ui: ChatUiContextValue,
  runId: string,
): ChatUiContextValue {
  const events = useRunEvents(ui.events, runId);
  return useStableValue({ ...ui, events }, shallowEqualObjects);
}

function sameMessage(left: UiMessage, right: UiMessage): boolean {
  return left === right || sameJson(left, right);
}

/**
 * Reuse the previous message object for each id whose content is equal, so
 * memoized message rows skip a render when a poll returns fresh JSON or an
 * event for another run arrives. Returns the previous array when nothing
 * changed at all.
 */
export function useStableMessages(messages: UiMessage[]): UiMessage[] {
  const ref = useRef<UiMessage[]>(messages);
  if (ref.current === messages) return messages;
  const previousById = new Map(
    ref.current.map((message) => [message.id, message]),
  );
  let changed = messages.length !== ref.current.length;
  const next = messages.map((message, index) => {
    const previous = previousById.get(message.id);
    const kept =
      previous && sameMessage(previous, message) ? previous : message;
    if (kept !== ref.current[index]) changed = true;
    return kept;
  });
  if (changed) ref.current = next;
  return ref.current;
}
