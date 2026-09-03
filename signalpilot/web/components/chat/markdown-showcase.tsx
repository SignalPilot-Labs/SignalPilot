"use client";

// Live playground for the chat markdown renderer: edit the source on the left,
// see exactly what a chat message would render on the right.

import { Columns2, Play, RotateCcw, Sparkles, Square } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { ChatMarkdown } from "~/components/chat/chat-markdown";
import {
  SHOWCASE_MARKDOWN,
  SHOWCASE_SECTIONS,
} from "~/lib/chat-markdown-showcase";

const STREAM_CHARS_PER_TICK = 28;
const STREAM_TICK_MS = 24;

export function MarkdownShowcase() {
  const [sectionId, setSectionId] = useState("all");
  const [source, setSource] = useState(SHOWCASE_MARKDOWN);
  const [streamedTo, setStreamedTo] = useState<number | null>(null);
  const [split, setSplit] = useState(true);
  const timer = useRef<number | null>(null);

  const stopStream = () => {
    if (timer.current !== null) {
      window.clearInterval(timer.current);
      timer.current = null;
    }
  };

  const [hydrated, setHydrated] = useState(false);
  useEffect(() => {
    setHydrated(true);
    return stopStream;
  }, []);

  const startStream = () => {
    stopStream();
    setStreamedTo(0);
    timer.current = window.setInterval(() => {
      setStreamedTo((position) => {
        const next = (position ?? 0) + STREAM_CHARS_PER_TICK;
        if (next >= source.length) {
          stopStream();
          return null;
        }
        return next;
      });
    }, STREAM_TICK_MS);
  };

  const select = (id: string) => {
    stopStream();
    setStreamedTo(null);
    setSectionId(id);
    setSource(
      id === "all"
        ? SHOWCASE_MARKDOWN
        : (SHOWCASE_SECTIONS.find((section) => section.id === id)?.markdown ??
            ""),
    );
  };

  const streaming = streamedTo !== null;
  const rendered = useMemo(
    () => (streaming ? source.slice(0, streamedTo ?? 0) : source),
    [source, streamedTo, streaming],
  );

  return (
    <div
      className="flex h-full flex-col overflow-hidden"
      data-testid="markdown-showcase"
      // Clicks before hydration are silently lost; tests gate on this flag.
      data-hydrated={hydrated ? "1" : "0"}
    >
      <header className="flex flex-wrap items-center gap-2 border-b border-[var(--color-border)] px-4 py-2.5">
        <h1 className="mr-2 text-[13px] font-medium text-[var(--color-text)]">
          Chat markdown
        </h1>
        <div className="flex flex-wrap gap-1">
          {[{ id: "all", title: "Everything" }, ...SHOWCASE_SECTIONS].map(
            (section) => (
              <button
                key={section.id}
                type="button"
                data-testid={`showcase-section-${section.id}`}
                onClick={() => select(section.id)}
                className={`rounded-lg px-2.5 py-1 text-[11.5px] transition-colors ${
                  sectionId === section.id
                    ? "bg-[var(--color-bg-hover)] text-[var(--color-text)]"
                    : "text-[var(--color-text-dim)] hover:text-[var(--color-text-muted)]"
                }`}
              >
                {section.title}
              </button>
            ),
          )}
        </div>
        <div className="ml-auto flex items-center gap-1">
          <button
            type="button"
            data-testid="showcase-stream"
            onClick={streaming ? stopStream : startStream}
            className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-[11.5px] text-[var(--color-text-dim)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
          >
            {streaming ? (
              <Square className="h-3 w-3" />
            ) : (
              <Play className="h-3 w-3" />
            )}
            {streaming ? "Stop" : "Replay as a stream"}
          </button>
          <button
            type="button"
            data-testid="showcase-layout"
            onClick={() => setSplit((value) => !value)}
            className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-[11.5px] text-[var(--color-text-dim)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
          >
            {split ? (
              <Sparkles className="h-3 w-3" />
            ) : (
              <Columns2 className="h-3 w-3" />
            )}
            {split ? "Transcript view" : "Split view"}
          </button>
          <button
            type="button"
            onClick={() => select(sectionId)}
            className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-[11.5px] text-[var(--color-text-dim)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
          >
            <RotateCcw className="h-3 w-3" />
            Reset
          </button>
        </div>
      </header>
      <div
        className={
          split
            ? "grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-2"
            : "flex min-h-0 flex-1 flex-col"
        }
      >
        {split && (
          <div className="flex min-h-0 flex-col border-r border-[var(--color-border)]">
            <p className="border-b border-[var(--color-border)] px-4 py-1.5 text-[10px] uppercase tracking-[0.16em] text-[var(--color-text-dim)]">
              Source
            </p>
            <textarea
              data-testid="showcase-source"
              value={source}
              spellCheck={false}
              onChange={(event) => {
                stopStream();
                setStreamedTo(null);
                setSource(event.target.value);
              }}
              className="min-h-0 flex-1 resize-none bg-[var(--color-bg-input)] px-4 py-3 font-mono text-[12px] leading-[1.7] text-[var(--color-text-muted)] outline-none"
            />
          </div>
        )}
        <div className="min-h-0 flex-1 overflow-auto">
          <p className="sticky top-0 z-10 border-b border-[var(--color-border)] bg-[var(--color-bg)] px-4 py-1.5 text-[10px] uppercase tracking-[0.16em] text-[var(--color-text-dim)]">
            {split ? "Rendered" : "Rendered at transcript width"}
          </p>
          {/* Transcript view reproduces the real message column: same max
              width, same avatar gutter, same page background. */}
          <div
            className={split ? "px-6 py-5" : "mx-auto w-full max-w-3xl px-6 py-6"}
            data-testid="showcase-rendered-outer"
          >
            <div className={split ? "" : "flex gap-3"}>
              {!split && (
                <div className="mt-0.5 flex h-7 w-7 flex-none items-center justify-center rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-card)]">
                  <Sparkles className="h-3.5 w-3.5 text-[var(--color-text-muted)]" />
                </div>
              )}
              <div className="min-w-0 flex-1" data-testid="showcase-rendered">
                <ChatMarkdown markdown={rendered} streaming={streaming} />
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
