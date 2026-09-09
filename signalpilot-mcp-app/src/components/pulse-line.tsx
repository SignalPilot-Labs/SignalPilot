import { useEffect, useRef } from "react";
import { cssVar, prefersReducedMotion, TAU } from "../motion";
import type { Chip, Phase, ToolKind } from "../types";

/**
 * The EKG strip: a quiet baseline with one spike per tool start and finish,
 * coloured by tool family, scrolling through the last sixty seconds. Terminal
 * phases freeze the trace and end it in the phase colour.
 */

const WINDOW_MS = 60_000;

type Spike = { at: number; amp: number; tone: string };

const TONE: Record<ToolKind, string> = {
  table: "--sp-text",
  table_list: "--sp-schema",
  schema: "--sp-schema",
  validation: "--sp-mint",
  dbt_run: "--sp-dbt",
  terminal: "--sp-muted",
  knowledge: "--sp-know",
  file: "--sp-mint",
  plan: "--sp-dim",
  web: "--sp-know",
  subagent: "--sp-muted",
  generic: "--sp-dim",
};

export function spikesFromChips(chips: Chip[], skewMs: number): Spike[] {
  const spikes: Spike[] = [];
  for (const chip of chips) {
    const started = Date.parse(chip.startedAt);
    if (Number.isFinite(started)) spikes.push({ at: started + skewMs, amp: 0.9, tone: TONE[chip.kind] });
    if (chip.endedAt) {
      const ended = Date.parse(chip.endedAt);
      if (Number.isFinite(ended)) {
        spikes.push({ at: ended + skewMs, amp: chip.status === "failed" ? -1 : 0.6, tone: chip.status === "failed" ? "--sp-err" : TONE[chip.kind] });
      }
    }
  }
  return spikes;
}

export function PulseLine({ chips, phase, skewMs, endedAt }: { chips: Chip[]; phase: Phase; skewMs: number; endedAt: string | null }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const model = useRef({ chips, phase, skewMs, endedAt });
  model.current = { chips, phase, skewMs, endedAt };

  useEffect(() => {
    const node = canvas.current;
    if (!node) return;
    const ctx = node.getContext("2d");
    if (!ctx) return;
    let frame = 0;
    let last = 0;
    const draw = (now: number) => {
      frame = requestAnimationFrame(draw);
      const still = prefersReducedMotion();
      const { chips: current, phase: currentPhase, skewMs: skew, endedAt: ended } = model.current;
      const terminal = currentPhase === "completed" || currentPhase === "failed" || currentPhase === "cancelled";
      // Frozen traces and reduced motion only need an occasional repaint.
      if ((terminal || still) && now - last < 1000) return;
      last = now;
      const width = node.clientWidth;
      const height = node.clientHeight;
      if (!width || !height) return;
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      if (node.width !== Math.round(width * dpr)) {
        node.width = Math.round(width * dpr);
        node.height = Math.round(height * dpr);
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, width, height);
      const base = height * 0.62;
      const endTime = terminal && ended ? Date.parse(ended) + skew : Date.now();
      const xOf = (ts: number) => width - ((endTime - ts) / WINDOW_MS) * width;
      ctx.lineWidth = 1.2;
      ctx.lineJoin = "round";
      ctx.lineCap = "round";
      ctx.beginPath();
      ctx.strokeStyle = cssVar(node, "--sp-border-2", "rgba(128,128,128,.3)");
      for (let x = 0; x <= width; x += 2) {
        const ts = endTime - ((width - x) / width) * WINDOW_MS;
        const idle = still || terminal ? 0 : Math.sin(ts / 380) * 0.6 + Math.sin(ts / 97) * 0.3;
        const y = base - idle;
        if (x === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
      for (const spike of spikesFromChips(current, skew)) {
        if (endTime - spike.at > WINDOW_MS || spike.at > endTime) continue;
        const x = xOf(spike.at);
        const amp = height * 0.42 * spike.amp;
        ctx.beginPath();
        ctx.strokeStyle = cssVar(node, spike.tone, "#00ff88");
        ctx.globalAlpha = 0.35 + 0.65 * (1 - (endTime - spike.at) / WINDOW_MS);
        ctx.moveTo(x - 7, base);
        ctx.lineTo(x - 4, base + amp * 0.18);
        ctx.lineTo(x - 1.5, base - amp);
        ctx.lineTo(x + 1.5, base + amp * 0.32);
        ctx.lineTo(x + 4, base);
        ctx.lineTo(x + 7, base);
        ctx.stroke();
        ctx.globalAlpha = 1;
      }
      if (terminal) {
        ctx.strokeStyle = cssVar(node, currentPhase === "completed" ? "--sp-mint" : currentPhase === "failed" ? "--sp-err" : "--sp-muted", "#00ff88");
        ctx.globalAlpha = 0.7;
        ctx.beginPath();
        ctx.moveTo(width - 14, base);
        ctx.lineTo(width, base);
        ctx.stroke();
        ctx.globalAlpha = 1;
      } else {
        const color = cssVar(node, currentPhase === "waiting" ? "--sp-warn" : "--sp-mint", "#00ff88");
        ctx.fillStyle = color;
        ctx.shadowColor = color;
        ctx.shadowBlur = still ? 0 : 6;
        ctx.beginPath();
        ctx.arc(width - 1.5, base, 1.8, 0, TAU);
        ctx.fill();
        ctx.shadowBlur = 0;
      }
    };
    frame = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame);
  }, []);

  return (
    <div className="ekg" aria-hidden>
      <canvas ref={canvas} />
    </div>
  );
}
