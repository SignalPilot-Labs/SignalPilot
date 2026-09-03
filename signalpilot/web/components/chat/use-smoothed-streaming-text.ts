"use client";

import { useEffect, useRef, useState } from "react";

export const STREAM_WORDS_PER_SECOND = 28;
export const STREAM_MAX_WORDS_PER_SECOND = 55;
const BACKLOG_WORDS_AT_MAX_RATE = 80;
const MAX_FRAME_ELAPSED_MS = 100;

/** Character offsets immediately after each whitespace-delimited word. */
export function streamingWordEnds(text: string): number[] {
  const matches = [...text.matchAll(/\S+/g)];
  return matches.map((match, index) =>
    index + 1 < matches.length ? matches[index + 1].index : text.length,
  );
}

/** Increase the drain speed as a backlog grows, without exceeding the cap. */
export function streamingWordRate(backlogWords: number): number {
  const pressure = Math.min(
    1,
    Math.max(0, backlogWords) / BACKLOG_WORDS_AT_MAX_RATE,
  );
  return (
    STREAM_WORDS_PER_SECOND +
    pressure * (STREAM_MAX_WORDS_PER_SECOND - STREAM_WORDS_PER_SECOND)
  );
}

function sliceToWord(text: string, ends: number[], wordCount: number): string {
  if (wordCount <= 0 || ends.length === 0) return "";
  if (wordCount >= ends.length) return text;
  return text.slice(0, ends[wordCount - 1]);
}

/**
 * Smooth only a text block that was observed while a run was streaming.
 * Completed history renders immediately. Once smoothing starts it drains the
 * remaining buffer even if the terminal event arrives in the same SSE batch.
 */
export function useSmoothedStreamingText({
  text,
  streaming,
  flush,
}: {
  text: string;
  streaming: boolean;
  flush: boolean;
}): { text: string; smoothing: boolean } {
  const startedStreamingRef = useRef(streaming);
  const targetRef = useRef(text);
  const initialEnds = streaming ? streamingWordEnds(text) : [];
  const initialWordCount = streaming ? Math.min(1, initialEnds.length) : initialEnds.length;
  const visibleWordsRef = useRef(initialWordCount);
  const visibleTextRef = useRef(
    streaming ? sliceToWord(text, initialEnds, initialWordCount) : text,
  );
  const frameRef = useRef<number | null>(null);
  const lastFrameRef = useRef<number | null>(null);
  const wordBudgetRef = useRef(0);
  const [visibleText, setVisibleText] = useState(visibleTextRef.current);
  const [smoothing, setSmoothing] = useState(
    streaming && initialEnds.length > 1,
  );

  if (streaming) startedStreamingRef.current = true;

  useEffect(() => {
    targetRef.current = text;
    const targetEnds = streamingWordEnds(text);
    const show = (value: string) => {
      visibleTextRef.current = value;
      setVisibleText(value);
    };

    if (flush || !startedStreamingRef.current) {
      visibleWordsRef.current = targetEnds.length;
      wordBudgetRef.current = 0;
      lastFrameRef.current = null;
      show(text);
      setSmoothing(false);
      return;
    }

    // A retry can replace the text accumulated for a run. Restart the visual
    // stream instead of revealing content from the abandoned attempt.
    if (!text.startsWith(visibleTextRef.current)) {
      visibleWordsRef.current = Math.min(1, targetEnds.length);
      wordBudgetRef.current = 0;
      lastFrameRef.current = null;
      show(sliceToWord(text, targetEnds, visibleWordsRef.current));
    }

    if (visibleWordsRef.current >= targetEnds.length) {
      visibleWordsRef.current = targetEnds.length;
      show(text);
      setSmoothing(false);
      return;
    }

    setSmoothing(true);
    if (frameRef.current !== null) return;

    const tick = (timestamp: number) => {
      const target = targetRef.current;
      const ends = streamingWordEnds(target);
      const previousTimestamp = lastFrameRef.current;
      lastFrameRef.current = timestamp;
      if (previousTimestamp !== null) {
        const elapsedMs = Math.min(
          MAX_FRAME_ELAPSED_MS,
          Math.max(0, timestamp - previousTimestamp),
        );
        const backlog = ends.length - visibleWordsRef.current;
        const rate = streaming
          ? streamingWordRate(backlog)
          : STREAM_MAX_WORDS_PER_SECOND;
        wordBudgetRef.current += (elapsedMs / 1_000) * rate;
        const advance = Math.min(backlog, Math.floor(wordBudgetRef.current));
        if (advance > 0) {
          wordBudgetRef.current -= advance;
          visibleWordsRef.current += advance;
          show(sliceToWord(target, ends, visibleWordsRef.current));
        }
      }

      if (visibleWordsRef.current < ends.length) {
        frameRef.current = requestAnimationFrame(tick);
      } else {
        frameRef.current = null;
        lastFrameRef.current = null;
        show(target);
        setSmoothing(false);
      }
    };
    frameRef.current = requestAnimationFrame(tick);

    return () => {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
      frameRef.current = null;
      lastFrameRef.current = null;
    };
  }, [flush, streaming, text]);

  useEffect(
    () => () => {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
    },
    [],
  );

  return { text: visibleText, smoothing };
}
