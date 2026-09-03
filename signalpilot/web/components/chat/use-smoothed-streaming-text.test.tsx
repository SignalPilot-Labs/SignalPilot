import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  STREAM_MAX_WORDS_PER_SECOND,
  STREAM_WORDS_PER_SECOND,
  streamingWordEnds,
  streamingWordRate,
  useSmoothedStreamingText,
} from "~/components/chat/use-smoothed-streaming-text";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

function Probe({
  text,
  streaming,
  flush = false,
}: {
  text: string;
  streaming: boolean;
  flush?: boolean;
}) {
  const value = useSmoothedStreamingText({ text, streaming, flush });
  return <span data-smoothing={String(value.smoothing)}>{value.text}</span>;
}

describe("streaming text smoothing", () => {
  let container: HTMLDivElement;
  let root: Root;
  let frameTime = 0;
  let nextFrame = 0;
  let frames = new Map<number, FrameRequestCallback>();

  const runFrames = async (durationMs: number) => {
    const frameCount = Math.ceil(durationMs / 16);
    for (let index = 0; index < frameCount; index += 1) {
      const callbacks = [...frames.values()];
      frames = new Map();
      frameTime += 16;
      await act(async () => {
        callbacks.forEach((callback) => callback(frameTime));
      });
    }
  };

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
      const id = ++nextFrame;
      frames.set(id, callback);
      return id;
    });
    vi.stubGlobal("cancelAnimationFrame", (id: number) => frames.delete(id));
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.unstubAllGlobals();
  });

  const shown = () => container.querySelector("span")?.textContent ?? "";

  it("retains whitespace while finding word boundaries", () => {
    expect(streamingWordEnds("  one  two\nthree")).toEqual([7, 11, 16]);
  });

  it("uses an adaptive rate with a hard maximum", () => {
    expect(streamingWordRate(0)).toBe(STREAM_WORDS_PER_SECOND);
    expect(streamingWordRate(40)).toBeGreaterThan(STREAM_WORDS_PER_SECOND);
    expect(streamingWordRate(80)).toBe(STREAM_MAX_WORDS_PER_SECOND);
    expect(streamingWordRate(8_000)).toBe(STREAM_MAX_WORDS_PER_SECOND);
  });

  it("reveals a live burst over time instead of all at once", async () => {
    const text = Array.from({ length: 100 }, (_, index) => `word${index}`).join(" ");
    await act(async () => root.render(<Probe text={text} streaming />));
    expect(shown()).toBe("word0 ");

    await runFrames(500);
    const revealed = shown().trim().split(/\s+/).length;
    expect(revealed).toBeGreaterThan(10);
    expect(revealed).toBeLessThan(30);
    expect(shown()).not.toBe(text);
  });

  it("renders completed history immediately and flushes for a tool boundary", async () => {
    const text = Array.from({ length: 60 }, (_, index) => `word${index}`).join(" ");
    await act(async () => root.render(<Probe text={text} streaming={false} />));
    expect(shown()).toBe(text);

    await act(async () => root.render(<Probe text={text} streaming flush />));
    expect(shown()).toBe(text);
  });

  it("continues draining after the run completes", async () => {
    const text = Array.from({ length: 40 }, (_, index) => `word${index}`).join(" ");
    await act(async () => root.render(<Probe text={text} streaming />));
    await act(async () => root.render(<Probe text={text} streaming={false} />));
    expect(shown()).not.toBe(text);

    await runFrames(1_000);
    expect(shown()).toBe(text);
  });
});
