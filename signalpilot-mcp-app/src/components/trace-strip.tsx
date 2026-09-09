import {
  BookOpen,
  Bot,
  CircleCheck,
  FileText,
  Globe,
  Layers,
  ListTodo,
  SquareTerminal,
  Table2,
  TableProperties,
  Waypoints,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { useLayoutEffect, useRef } from "react";
import type { Chip, ToolKind } from "../types";

/**
 * One chip per top-level tool call. The row never wraps or scrolls: chips
 * that do not fit are hidden from the left behind a "+N" counter. Visibility
 * is owned by the layout effect (DOM `hidden`), not by React state, so the
 * measurement always sees every chip. Chips are display only: no hover,
 * click or focus behaviour.
 */

const ICON: Record<ToolKind, LucideIcon> = {
  table: Table2,
  table_list: Layers,
  schema: TableProperties,
  validation: CircleCheck,
  dbt_run: Waypoints,
  terminal: SquareTerminal,
  knowledge: BookOpen,
  file: FileText,
  plan: ListTodo,
  web: Globe,
  subagent: Bot,
  generic: Wrench,
};

export function fitChips(strip: HTMLElement): number {
  const items = [...strip.querySelectorAll<HTMLElement>(".chip:not(.more)")];
  const counter = strip.querySelector<HTMLElement>(".chip.more");
  items.forEach((item) => (item.hidden = false));
  if (counter) counter.hidden = true;
  const fits = () => strip.scrollWidth <= strip.clientWidth + 1;
  let hidden = 0;
  while (!fits() && hidden < items.length - 1) {
    if (counter) {
      counter.hidden = false;
      counter.textContent = `+${hidden + 1}`;
      counter.setAttribute("aria-label", `${hidden + 1} earlier tools`);
    }
    items[hidden]!.hidden = true;
    hidden += 1;
  }
  if (counter && hidden === 0) counter.hidden = true;
  return hidden;
}

export function TraceStrip({ chips }: { chips: Chip[] }) {
  const strip = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const node = strip.current;
    if (!node) return;
    fitChips(node);
    const observer = new ResizeObserver(() => fitChips(node));
    observer.observe(node);
    return () => observer.disconnect();
  });

  return (
    <div className="strip" ref={strip} role="list" aria-label="Tool activity">
      <span className="chip more" hidden />
      {chips.map((chip) => {
        const Icon = ICON[chip.kind];
        return (
          <span
            key={chip.id}
            role="listitem"
            className="chip"
            data-status={chip.status}
            data-kind={chip.kind}
            aria-label={`${chip.detail}${chip.stat ? `, ${chip.stat}` : ""}`}
          >
            <Icon aria-hidden />
            <span className="label">{chip.label}</span>
            {chip.stat && <span className="stat-t">{chip.stat}</span>}
          </span>
        );
      })}
    </div>
  );
}
