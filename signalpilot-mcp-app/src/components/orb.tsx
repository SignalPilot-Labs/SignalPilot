import { useEffect, useRef } from "react";
import { cssVar, prefersReducedMotion, TAU } from "../motion";
import type { Phase, Plan } from "../types";

/**
 * The panel's face: one canvas ring whose figure encodes the run phase.
 * Phase changes crossfade over 420 ms; reduced motion draws each phase at
 * rest. Plan progress, when known, wraps the ring as segments.
 */

const CROSSFADE_MS = 420;
const SETTLE_MS = 1500;

export type Palette = { mint: string; warn: string; err: string; dim: string; text: string; muted: string; sans: string };

function readPalette(element: Element): Palette {
  return {
    mint: cssVar(element, "--sp-mint", "#00ff88"),
    warn: cssVar(element, "--sp-warn", "#ffaa00"),
    err: cssVar(element, "--sp-err", "#ff4444"),
    dim: cssVar(element, "--sp-border-2", "rgba(128,128,128,.4)"),
    text: cssVar(element, "--sp-text", "#ededed"),
    muted: cssVar(element, "--sp-muted", "#9c9c96"),
    sans: cssVar(element, "--sp-sans", "system-ui, sans-serif"),
  };
}

function phaseColor(phase: Phase, palette: Palette): string {
  if (phase === "waiting") return palette.warn;
  if (phase === "failed") return palette.err;
  if (phase === "cancelled") return palette.muted;
  return palette.mint;
}

const isTerminal = (phase: Phase) => phase === "completed" || phase === "failed" || phase === "cancelled";

export type Frame = { phase: Phase; t: number; since: number; alpha: number; still: boolean; plan: Plan | null };

export function drawOrb(ctx: CanvasRenderingContext2D, size: number, palette: Palette, frame: Frame) {
  const { phase, t, since, alpha, still, plan } = frame;
  const c = size / 2;
  const r = size * 0.4;
  const w = Math.max(2, size * 0.045);
  const col = phaseColor(phase, palette);
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.lineCap = "round";
  ctx.lineWidth = w;
  const ring = (a0: number, a1: number, color: string, lw = w, dash: number[] = []) => {
    ctx.beginPath();
    ctx.setLineDash(dash);
    ctx.lineWidth = lw;
    ctx.strokeStyle = color;
    ctx.arc(c, c, r, a0, a1);
    ctx.stroke();
    ctx.setLineDash([]);
  };
  if (plan && phase !== "booting") {
    const gap = 0.12;
    for (let i = 0; i < plan.total; i++) {
      const a0 = -TAU / 4 + (i / plan.total) * TAU + gap / 2;
      const a1 = -TAU / 4 + ((i + 1) / plan.total) * TAU - gap / 2;
      ring(a0, a1, i < plan.done ? col : palette.dim, w * 0.55, i < plan.done ? [] : [2, 3]);
    }
    ctx.translate(c, c);
    ctx.scale(0.8, 0.8);
    ctx.translate(-c, -c);
  }

  if (phase === "booting") {
    const segments = 12;
    const progress = Math.min(1, since / 2000);
    const rotation = still ? 0 : t * 0.6;
    for (let i = 0; i < segments; i++) {
      if (i / segments > progress) break;
      const a0 = rotation + (i / segments) * TAU;
      ring(a0, a0 + (TAU / segments) * 0.6, col, w * 0.8);
    }
    ctx.globalAlpha = alpha * 0.55;
    ring(0, TAU, palette.dim, 1);
  } else if (phase === "thinking") {
    const breathe = still ? 1 : 1 + 0.06 * Math.sin((t * TAU) / 2.4);
    ctx.save();
    ctx.translate(c, c);
    ctx.scale(breathe, breathe);
    ctx.translate(-c, -c);
    ring(0, TAU, palette.dim, w * 0.9);
    ctx.restore();
    const dx = still ? 0 : Math.sin(t * 1.3) * r * 0.28;
    const dy = still ? 0 : Math.cos(t * 0.9) * r * 0.22;
    ctx.beginPath();
    ctx.fillStyle = palette.muted;
    ctx.arc(c + dx, c + dy, w * 1.1, 0, TAU);
    ctx.fill();
  } else if (phase === "tool") {
    ring(0, TAU, palette.dim, w * 0.7);
    const angle = still ? -TAU / 4 : ((t * TAU) / 1.8) % TAU;
    ctx.shadowColor = col;
    ctx.shadowBlur = size * 0.12;
    ring(angle, angle + TAU * 0.22, col);
    ctx.shadowBlur = 0;
    ctx.beginPath();
    ctx.fillStyle = col;
    ctx.globalAlpha = alpha * (still ? 1 : 0.6 + 0.4 * Math.sin(t * 4));
    ctx.arc(c, c, w * 0.9, 0, TAU);
    ctx.fill();
  } else if (phase === "writing") {
    ring(0, TAU, col, w * 0.7);
    const bars = 4;
    const bw = Math.max(2, size * 0.035);
    const gap = bw * 1.6;
    const total = bars * bw + (bars - 1) * gap;
    for (let i = 0; i < bars; i++) {
      const wave = still ? 0.7 : 0.4 + 0.6 * (0.5 + 0.5 * Math.sin((t * TAU) / 0.9 - i * 0.7));
      const h = r * 0.8 * wave;
      const x = c - total / 2 + i * (bw + gap);
      ctx.fillStyle = palette.text;
      ctx.beginPath();
      ctx.roundRect(x, c - h / 2, bw, h, bw / 2);
      ctx.fill();
    }
  } else if (phase === "waiting") {
    const cycle = (t * 1000) % 3000;
    const knock = still || cycle > 500 ? 0 : Math.max(0, Math.sin((cycle / 3000) * TAU * 2)) * size * 0.03;
    ctx.save();
    ctx.translate(0, -knock);
    ring(-TAU / 4 + 0.45, -TAU / 4 + TAU - 0.45, col);
    ctx.fillStyle = col;
    ctx.font = `600 ${size * 0.36}px ${palette.sans}`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText("?", c, c + size * 0.02);
    ctx.restore();
  } else if (phase === "completed") {
    const p = still ? 1 : Math.min(1, since / 700);
    const eased = 1 - Math.pow(1 - p, 3);
    ring(-TAU / 4, -TAU / 4 + TAU * eased, col);
    if (p > 0.5) {
      const q = still ? 1 : Math.min(1, (since - 350) / 350);
      const p0 = { x: c - r * 0.42, y: c + r * 0.02 };
      const p1 = { x: c - r * 0.1, y: c + r * 0.34 };
      const p2 = { x: c + r * 0.45, y: c - r * 0.3 };
      const l1 = Math.hypot(p1.x - p0.x, p1.y - p0.y);
      const l2 = Math.hypot(p2.x - p1.x, p2.y - p1.y);
      const d = q * (l1 + l2);
      ctx.beginPath();
      ctx.strokeStyle = col;
      ctx.lineWidth = w * 1.1;
      ctx.moveTo(p0.x, p0.y);
      if (d <= l1) {
        const k = d / l1;
        ctx.lineTo(p0.x + (p1.x - p0.x) * k, p0.y + (p1.y - p0.y) * k);
      } else {
        ctx.lineTo(p1.x, p1.y);
        const k = (d - l1) / l2;
        ctx.lineTo(p1.x + (p2.x - p1.x) * k, p1.y + (p2.y - p1.y) * k);
      }
      ctx.stroke();
    }
  } else {
    // failed and cancelled: the ring breaks into two arcs; failed adds one shake.
    const shake = phase === "failed" && !still && since < 400 ? Math.sin((since / 400) * TAU * 2) * size * 0.02 : 0;
    ctx.save();
    ctx.translate(shake, 0);
    ring(0.25, Math.PI - 0.25, col);
    ring(Math.PI + 0.25, TAU - 0.25, col);
    ctx.beginPath();
    ctx.strokeStyle = col;
    ctx.lineWidth = w;
    const k = r * 0.3;
    if (phase === "failed") {
      ctx.moveTo(c - k, c - k);
      ctx.lineTo(c + k, c + k);
      ctx.moveTo(c + k, c - k);
      ctx.lineTo(c - k, c + k);
    } else {
      ctx.moveTo(c - k, c);
      ctx.lineTo(c + k, c);
    }
    ctx.stroke();
    ctx.restore();
  }
  ctx.restore();
}

export function Orb({ phase, plan, onClick, label }: { phase: Phase; plan: Plan | null; onClick: () => void; label: string }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const model = useRef({ phase, prior: phase, at: performance.now(), plan });
  if (model.current.phase !== phase) {
    model.current = { phase, prior: model.current.phase, at: performance.now(), plan };
  }
  model.current.plan = plan;

  useEffect(() => {
    const node = canvas.current;
    if (!node) return;
    const ctx = node.getContext("2d");
    if (!ctx) return;
    let frame = 0;
    let paletteAt = 0;
    let palette = readPalette(node);
    let restingKey = "";
    const draw = (now: number) => {
      frame = requestAnimationFrame(draw);
      const { phase: current, prior, at, plan: currentPlan } = model.current;
      const still = prefersReducedMotion();
      const since = now - at;
      // A settled terminal orb (or reduced motion) is static: paint once per
      // phase/plan/size combination, then idle.
      const resting = still || (isTerminal(current) && since > SETTLE_MS);
      const key = `${current}:${currentPlan?.done ?? ""}/${currentPlan?.total ?? ""}:${node.clientWidth}`;
      if (resting && restingKey === key) return;
      restingKey = resting ? key : "";
      const size = node.clientWidth || 72;
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      const px = Math.round(size * dpr);
      if (node.width !== px) {
        node.width = px;
        node.height = px;
      }
      if (now - paletteAt > 1000) {
        palette = readPalette(node);
        paletteAt = now;
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, size, size);
      const mix = still ? 1 : Math.min(1, since / CROSSFADE_MS);
      const t = now / 1000;
      if (mix < 1) drawOrb(ctx, size, palette, { phase: prior, t, since: 10_000, alpha: 1 - mix, still, plan: currentPlan });
      drawOrb(ctx, size, palette, { phase: current, t, since, alpha: mix, still, plan: currentPlan });
    };
    frame = requestAnimationFrame(draw);
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const wake = () => {
      restingKey = "";
      paletteAt = 0;
    };
    media.addEventListener("change", wake);
    const observer = new ResizeObserver(wake);
    observer.observe(node);
    return () => {
      cancelAnimationFrame(frame);
      media.removeEventListener("change", wake);
      observer.disconnect();
    };
  }, []);

  return (
    <button type="button" className="orb" onClick={onClick} aria-label={label} data-phase={phase}>
      <canvas ref={canvas} aria-hidden />
    </button>
  );
}
