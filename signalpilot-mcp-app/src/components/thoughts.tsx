import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { Thought } from "../thoughts";

/**
 * Three rows, newest at the bottom and brightest. Rows are absolutely
 * positioned from measured heights so a two-line thought never pushes the
 * strip below; the oldest row clips at the top instead. Departing rows fade
 * upward for 450 ms before they leave the DOM.
 */

const ROW_GAP = 4;
const EXIT_MS = 450;

export function Thoughts({ thoughts, writing, empty }: { thoughts: Thought[]; writing: boolean; empty: string }) {
  const container = useRef<HTMLDivElement>(null);
  const [leaving, setLeaving] = useState<Thought[]>([]);
  const previous = useRef<Thought[]>(thoughts);

  useEffect(() => {
    const ids = new Set(thoughts.map((thought) => thought.id));
    const gone = previous.current.filter((thought) => !ids.has(thought.id));
    previous.current = thoughts;
    if (!gone.length) return;
    setLeaving((current) => [...current, ...gone]);
    const timer = setTimeout(() => {
      const goneIds = new Set(gone.map((thought) => thought.id));
      setLeaving((current) => current.filter((thought) => !goneIds.has(thought.id)));
    }, EXIT_MS);
    return () => clearTimeout(timer);
  }, [thoughts]);

  // Position live rows from the bottom up after every render.
  useLayoutEffect(() => {
    const node = container.current;
    if (!node) return;
    const rows = [...node.querySelectorAll<HTMLElement>(".t.live")];
    // Rows read top-down while they fit; once they overflow, the newest row
    // pins to the bottom and the oldest clips at the top.
    const total = rows.reduce((sum, el) => sum + el.offsetHeight, 0) + Math.max(0, rows.length - 1) * ROW_GAP;
    let y = Math.min(node.clientHeight, total);
    for (let i = rows.length - 1; i >= 0; i--) {
      const el = rows[i]!;
      y -= el.offsetHeight;
      el.style.transform = `translateY(${y}px)`;
      el.dataset.age = String(rows.length - 1 - i);
      if (el.dataset.entered !== "true") {
        el.dataset.entered = "true";
        el.classList.add("in");
        requestAnimationFrame(() => requestAnimationFrame(() => el.classList.remove("in")));
      }
      y -= ROW_GAP;
    }
  });

  const last = thoughts.at(-1);
  return (
    <div className="thoughts" ref={container} aria-live="polite">
      {thoughts.length === 0 && leaving.length === 0 && <div className="t live empty" data-age="0">{empty}</div>}
      {leaving.map((thought) => (
        <div key={`gone-${thought.id}`} className="t leaving" aria-hidden>
          {thought.text}
        </div>
      ))}
      {thoughts.map((thought) => (
        <div key={thought.id} className="t live">
          {thought.text}
          {writing && thought === last && <span className="caret" aria-hidden>▍</span>}
        </div>
      ))}
    </div>
  );
}
