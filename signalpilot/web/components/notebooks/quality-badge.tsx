import type { CSSProperties } from "react";

const SCORE_HIGH = 80;
const SCORE_MID = 50;

type ScoreLevel = "high" | "mid" | "low";

function scoreLevel(score: number): ScoreLevel {
  if (score >= SCORE_HIGH) return "high";
  if (score >= SCORE_MID) return "mid";
  return "low";
}

const LEVEL_STYLES: Record<
  ScoreLevel,
  { color: string; bg: string; border: string }
> = {
  high: {
    color: "var(--color-success)",
    bg: "color-mix(in srgb, var(--color-success) 10%, transparent)",
    border: "color-mix(in srgb, var(--color-success) 25%, transparent)",
  },
  mid: {
    color: "var(--color-warning)",
    bg: "color-mix(in srgb, var(--color-warning) 10%, transparent)",
    border: "color-mix(in srgb, var(--color-warning) 25%, transparent)",
  },
  low: {
    color: "var(--color-error)",
    bg: "color-mix(in srgb, var(--color-error) 10%, transparent)",
    border: "color-mix(in srgb, var(--color-error) 25%, transparent)",
  },
};

interface QualityBadgeProps {
  score: number | null | undefined;
  /** Visual size variant — "sm" for list cards, "md" for detail header */
  size?: "sm" | "md";
}

export function QualityBadge({ score, size = "sm" }: QualityBadgeProps) {
  if (score === null || score === undefined) return null;

  const level = scoreLevel(score);
  const { color, bg, border } = LEVEL_STYLES[level];

  const style: CSSProperties = {
    color,
    backgroundColor: bg,
    borderColor: border,
  };

  const sizeClass =
    size === "md"
      ? "px-2.5 py-1 text-[11px] tracking-[0.12em]"
      : "px-1.5 py-0.5 text-[10px] tracking-wider";

  return (
    <span
      style={style}
      className={`inline-flex items-center gap-1 border font-mono uppercase select-none ${sizeClass}`}
      aria-label={`Quality score: ${score} out of 100`}
      title={`Quality score: ${score}/100`}
    >
      <span className="opacity-70">QS</span>
      <span>{score}</span>
    </span>
  );
}

export type { QualityBadgeProps };
