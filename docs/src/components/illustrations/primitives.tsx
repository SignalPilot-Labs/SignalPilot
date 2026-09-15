import type {CSSProperties, ReactNode} from 'react';
import clsx from 'clsx';
import styles from './illustrations.module.css';

/* Shared vocabulary for the "annotated schematic" illustration set.
   Every colour is a CSS token so the same SVG works in both themes.
   Strokes are 1.5-2px, fills are always explicit, labels are tiny mono. */

export const STROKE = 'var(--sp-ill-stroke, var(--sp-line-2))';
export const STROKE_SOFT = 'var(--sp-line)';
export const FILL = 'var(--sp-card-solid)';
export const FILL_TINT = 'var(--sp-card)';
export const ACCENT = 'var(--sp-mint)';
export const ACCENT_SOFT = 'var(--sp-glow)';
export const BLUE = 'var(--sp-blue)';
export const AMBER = 'var(--sp-amber)';
export const RED = 'var(--sp-red)';
export const TEXT = 'var(--sp-text)';
export const MUTED = 'var(--sp-muted)';
export const DIM = 'var(--sp-dim)';
export const MONO = 'var(--sp-font-mono)';

export type IllustrationProps = {
  className?: string;
  /** Rendered width. Number = px, string = any CSS length. Defaults to 100%. */
  size?: number | string;
  /** Accessible name. Omit to mark the drawing decorative. */
  title?: string;
  style?: CSSProperties;
};

type FrameProps = IllustrationProps & {
  width: number;
  height: number;
  children: ReactNode;
};

export function Frame({
  className,
  size,
  title,
  style,
  width,
  height,
  children,
}: FrameProps) {
  const w = size === undefined ? '100%' : typeof size === 'number' ? `${size}px` : size;
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      role={title ? 'img' : 'presentation'}
      aria-label={title}
      aria-hidden={title ? undefined : true}
      className={clsx(styles.svg, className)}
      style={{width: w, aspectRatio: `${width} / ${height}`, ...style}}
      fill="none"
      strokeLinecap="round"
      strokeLinejoin="round">
      {title ? <title>{title}</title> : null}
      {children}
    </svg>
  );
}

type NodeProps = {
  x: number;
  y: number;
  w: number;
  h: number;
  r?: number;
  fill?: string;
  stroke?: string;
  strokeWidth?: number;
  dashed?: boolean;
};

/** Rounded-rect node — the basic building block. */
export function Node({
  x,
  y,
  w,
  h,
  r = 8,
  fill = FILL,
  stroke = STROKE,
  strokeWidth = 1.5,
  dashed,
}: NodeProps) {
  return (
    <rect
      x={x}
      y={y}
      width={w}
      height={h}
      rx={r}
      fill={fill}
      stroke={stroke}
      strokeWidth={strokeWidth}
      strokeDasharray={dashed ? '4 4' : undefined}
    />
  );
}

type LabelProps = {
  x: number;
  y: number;
  children: string;
  size?: number;
  color?: string;
  anchor?: 'start' | 'middle' | 'end';
  weight?: number;
  upper?: boolean;
};

/** Tiny monospace annotation. */
export function Label({
  x,
  y,
  children,
  size = 11,
  color = DIM,
  anchor = 'start',
  weight = 500,
  upper,
}: LabelProps) {
  return (
    <text
      x={x}
      y={y}
      fontFamily={MONO}
      fontSize={size}
      fontWeight={weight}
      fill={color}
      textAnchor={anchor}
      letterSpacing={upper ? 0.8 : 0}
      style={{textTransform: upper ? 'uppercase' : undefined}}>
      {children}
    </text>
  );
}

type WireProps = {
  d: string;
  dashed?: boolean;
  stroke?: string;
  strokeWidth?: number;
};

/** Connector line. Dashed by default — it reads as "flow", not "edge". */
export function Wire({d, dashed = true, stroke = STROKE, strokeWidth = 1.5}: WireProps) {
  return (
    <path
      d={d}
      stroke={stroke}
      strokeWidth={strokeWidth}
      strokeDasharray={dashed ? '3 5' : undefined}
      fill="none"
    />
  );
}

/** Small arrowhead pointing right, placed with its tip at (x, y). */
export function Arrow({x, y, color = STROKE, dir = 'right'}: {x: number; y: number; color?: string; dir?: 'right' | 'down' | 'left' | 'up'}) {
  const rot = {right: 0, down: 90, left: 180, up: 270}[dir];
  return (
    <path
      d="M-6 -4 L0 0 L-6 4"
      transform={`translate(${x} ${y}) rotate(${rot})`}
      stroke={color}
      strokeWidth={1.5}
      fill="none"
    />
  );
}

type CylinderProps = {
  x: number;
  y: number;
  w: number;
  h: number;
  fill?: string;
  stroke?: string;
  accent?: boolean;
};

/** Database cylinder. */
export function Cylinder({x, y, w, h, fill = FILL, stroke = STROKE, accent}: CylinderProps) {
  const ry = Math.max(5, w * 0.14);
  return (
    <g>
      <path
        d={`M${x} ${y + ry} v${h - ry * 2} a${w / 2} ${ry} 0 0 0 ${w} 0 v-${h - ry * 2}`}
        fill={fill}
        stroke={stroke}
        strokeWidth={1.5}
      />
      <ellipse cx={x + w / 2} cy={y + ry} rx={w / 2} ry={ry} fill={fill} stroke={stroke} strokeWidth={1.5} />
      {accent ? (
        <path d={`M${x} ${y + ry + 10} a${w / 2} ${ry} 0 0 0 ${w} 0`} stroke={ACCENT} strokeWidth={1.5} fill="none" />
      ) : null}
    </g>
  );
}

/** Shield with a check — "governed". */
export function Shield({x, y, s = 22, color = ACCENT}: {x: number; y: number; s?: number; color?: string}) {
  const k = s / 22;
  return (
    <g transform={`translate(${x} ${y}) scale(${k})`}>
      <path
        d="M11 1 L20 4.5 V11 C20 16.5 16 20.5 11 22 C6 20.5 2 16.5 2 11 V4.5 Z"
        fill={FILL}
        stroke={color}
        strokeWidth={1.6}
      />
      <path d="M7 11.5 L10 14.5 L15 8.5" stroke={color} strokeWidth={1.8} fill="none" />
    </g>
  );
}

/** Check mark glyph in a circle. */
export function CheckDot({x, y, color = ACCENT, r = 7}: {x: number; y: number; color?: string; r?: number}) {
  const k = r / 7;
  return (
    <g transform={`translate(${x} ${y}) scale(${k})`}>
      <circle r={7} fill={FILL} stroke={color} strokeWidth={1.5} />
      <path d="M-3 0.2 L-0.8 2.4 L3.2 -2.2" stroke={color} strokeWidth={1.6} fill="none" />
    </g>
  );
}

/** Cross glyph in a circle — "blocked". */
export function CrossDot({x, y, color = RED, r = 7}: {x: number; y: number; color?: string; r?: number}) {
  const k = r / 7;
  return (
    <g transform={`translate(${x} ${y}) scale(${k})`}>
      <circle r={7} fill={FILL} stroke={color} strokeWidth={1.5} />
      <path d="M-2.6 -2.6 L2.6 2.6 M2.6 -2.6 L-2.6 2.6" stroke={color} strokeWidth={1.6} fill="none" />
    </g>
  );
}

/** Horizontal "text" placeholder bar. */
export function Bar({x, y, w, h = 4, color = STROKE_SOFT}: {x: number; y: number; w: number; h?: number; color?: string}) {
  return <rect x={x} y={y} width={w} height={h} rx={h / 2} fill={color} />;
}

/** Window / app frame with three dots. */
export function Window({x, y, w, h, fill = FILL}: {x: number; y: number; w: number; h: number; fill?: string}) {
  return (
    <g>
      <Node x={x} y={y} w={w} h={h} r={10} fill={fill} />
      <line x1={x} y1={y + 20} x2={x + w} y2={y + 20} stroke={STROKE_SOFT} strokeWidth={1.5} />
      <circle cx={x + 11} cy={y + 10} r={2.2} fill={STROKE} />
      <circle cx={x + 19} cy={y + 10} r={2.2} fill={STROKE} />
      <circle cx={x + 27} cy={y + 10} r={2.2} fill={STROKE} />
    </g>
  );
}
