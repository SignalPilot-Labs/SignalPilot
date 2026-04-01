"use client";

import { useRef, useState, useEffect } from "react";

/**
 * Lightweight SVG-based data visualization components.
 * No external dependencies — pure SVG for minimal bundle impact.
 */

/**
 * Mini sparkline chart.
 */
export function Sparkline({
  values,
  width = 80,
  height = 20,
  color = "var(--color-text-dim)",
  fillOpacity = 0.05,
}: {
  values: number[];
  width?: number;
  height?: number;
  color?: string;
  fillOpacity?: number;
}) {
  if (values.length < 2) return null;
  const max = Math.max(...values, 1);
  const min = Math.min(...values, 0);
  const range = max - min || 1;

  const points = values.map((v, i) => ({
    x: (i / (values.length - 1)) * width,
    y: height - ((v - min) / range) * height,
  }));

  const linePoints = points.map(p => `${p.x},${p.y}`).join(" ");
  const fillPoints = `0,${height} ${linePoints} ${width},${height}`;

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="flex-shrink-0">
      {/* Fill area */}
      <polygon points={fillPoints} fill={color} opacity={fillOpacity} />
      {/* Line */}
      <polyline
        points={linePoints}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* End dot */}
      <circle
        cx={points[points.length - 1].x}
        cy={points[points.length - 1].y}
        r="2"
        fill={color}
      />
    </svg>
  );
}

/**
 * Mini donut/ring chart for showing a single percentage.
 */
export function RingGauge({
  value,
  max = 100,
  size = 32,
  strokeWidth = 3,
  color = "var(--color-success)",
  bgColor = "var(--color-border)",
}: {
  value: number;
  max?: number;
  size?: number;
  strokeWidth?: number;
  color?: string;
  bgColor?: string;
}) {
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const pct = Math.min(value / max, 1);
  const dashOffset = circumference * (1 - pct);

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="flex-shrink-0 -rotate-90">
      {/* Background ring */}
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke={bgColor}
        strokeWidth={strokeWidth}
      />
      {/* Value ring */}
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke={color}
        strokeWidth={strokeWidth}
        strokeDasharray={circumference}
        strokeDashoffset={dashOffset}
        strokeLinecap="square"
        className="transition-all duration-500"
      />
    </svg>
  );
}

/**
 * Horizontal bar chart — mini version for inline use.
 */
export function MiniBar({
  value,
  max = 100,
  width = 60,
  height = 4,
  color = "var(--color-success)",
  bgColor = "var(--color-bg)",
}: {
  value: number;
  max?: number;
  width?: number;
  height?: number;
  color?: string;
  bgColor?: string;
}) {
  const pct = Math.min(value / max, 1);

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="flex-shrink-0">
      <rect width={width} height={height} fill={bgColor} />
      <rect
        width={width * pct}
        height={height}
        fill={color}
        className="transition-all duration-300"
      />
    </svg>
  );
}

/**
 * Activity heatmap — shows density of events over time slots.
 */
export function ActivityDots({
  values,
  rows = 3,
  cols = 12,
  dotSize = 6,
  gap = 2,
  activeColor = "var(--color-success)",
  inactiveColor = "var(--color-border)",
}: {
  values: number[];
  rows?: number;
  cols?: number;
  dotSize?: number;
  gap?: number;
  activeColor?: string;
  inactiveColor?: string;
}) {
  const max = Math.max(...values, 1);
  const totalW = cols * (dotSize + gap) - gap;
  const totalH = rows * (dotSize + gap) - gap;

  return (
    <svg width={totalW} height={totalH} viewBox={`0 0 ${totalW} ${totalH}`} className="flex-shrink-0">
      {Array.from({ length: rows * cols }, (_, i) => {
        const row = Math.floor(i / cols);
        const col = i % cols;
        const val = values[i] ?? 0;
        const intensity = val / max;

        return (
          <rect
            key={i}
            x={col * (dotSize + gap)}
            y={row * (dotSize + gap)}
            width={dotSize}
            height={dotSize}
            fill={val > 0 ? activeColor : inactiveColor}
            opacity={val > 0 ? Math.max(0.2, intensity) : 0.15}
          />
        );
      })}
    </svg>
  );
}

/**
 * Mini vertical bar chart for distribution data.
 */
export function MiniBarChart({
  values,
  width = 80,
  height = 24,
  color = "var(--color-text-dim)",
  activeColor = "var(--color-success)",
  highlightLast = false,
}: {
  values: number[];
  width?: number;
  height?: number;
  color?: string;
  activeColor?: string;
  highlightLast?: boolean;
}) {
  if (values.length === 0) return null;
  const max = Math.max(...values, 1);
  const barWidth = Math.max(1, (width - (values.length - 1)) / values.length);
  const gap = 1;

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="flex-shrink-0">
      {values.map((v, i) => {
        const barH = Math.max(1, (v / max) * height);
        const isLast = highlightLast && i === values.length - 1;
        return (
          <rect
            key={i}
            x={i * (barWidth + gap)}
            y={height - barH}
            width={barWidth}
            height={barH}
            fill={isLast ? activeColor : color}
            opacity={isLast ? 1 : 0.5}
            className="transition-all duration-200"
          />
        );
      })}
    </svg>
  );
}

/**
 * Trend indicator — up/down/flat arrow with percentage.
 */
export function TrendIndicator({
  current,
  previous,
  size = 12,
  invertColors = false,
}: {
  current: number;
  previous: number;
  size?: number;
  invertColors?: boolean;
}) {
  if (previous === 0) return null;
  const pctChange = ((current - previous) / previous) * 100;
  const isUp = pctChange > 1;
  const isDown = pctChange < -1;

  const upColor = invertColors ? "var(--color-error)" : "var(--color-success)";
  const downColor = invertColors ? "var(--color-success)" : "var(--color-error)";
  const flatColor = "var(--color-text-dim)";

  const color = isUp ? upColor : isDown ? downColor : flatColor;

  return (
    <span className="inline-flex items-center gap-0.5">
      <svg width={size} height={size} viewBox="0 0 12 12" fill="none" className="flex-shrink-0">
        {isUp ? (
          <path d="M6 2L10 8H2L6 2Z" fill={color} />
        ) : isDown ? (
          <path d="M6 10L2 4H10L6 10Z" fill={color} />
        ) : (
          <rect x="2" y="5" width="8" height="2" fill={color} />
        )}
      </svg>
      <span className="text-[9px] tabular-nums" style={{ color }}>
        {Math.abs(pctChange).toFixed(1)}%
      </span>
    </span>
  );
}

/**
 * Horizontal stacked bar — shows distribution of categories.
 */
export function StackedBar({
  segments,
  width = 120,
  height = 6,
}: {
  segments: { value: number; color: string; label?: string }[];
  width?: number;
  height?: number;
}) {
  const total = segments.reduce((sum, s) => sum + s.value, 0) || 1;
  let offset = 0;

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="flex-shrink-0">
      <rect width={width} height={height} fill="var(--color-bg)" rx="0" />
      {segments.map((seg, i) => {
        const w = (seg.value / total) * width;
        const x = offset;
        offset += w;
        return (
          <rect
            key={i}
            x={x}
            y={0}
            width={Math.max(0, w - 0.5)}
            height={height}
            fill={seg.color}
            opacity={0.8}
            className="transition-all duration-300"
          >
            {seg.label && <title>{seg.label}: {seg.value}</title>}
          </rect>
        );
      })}
    </svg>
  );
}

/**
 * Area chart with gradient fill — larger version of sparkline for detail views.
 */
export function AreaChart({
  values,
  width = 200,
  height = 60,
  color = "var(--color-success)",
  showGrid = true,
}: {
  values: number[];
  width?: number;
  height?: number;
  color?: string;
  showGrid?: boolean;
}) {
  if (values.length < 2) return null;
  const padding = 2;
  const chartW = width - padding * 2;
  const chartH = height - padding * 2;
  const max = Math.max(...values, 1);
  const min = Math.min(...values, 0);
  const range = max - min || 1;

  const points = values.map((v, i) => ({
    x: padding + (i / (values.length - 1)) * chartW,
    y: padding + chartH - ((v - min) / range) * chartH,
  }));

  const linePath = points.map((p, i) => `${i === 0 ? "M" : "L"}${p.x},${p.y}`).join(" ");
  const fillPath = `M${padding},${height - padding} ${points.map(p => `L${p.x},${p.y}`).join(" ")} L${width - padding},${height - padding}Z`;

  const gridLines = showGrid ? [0.25, 0.5, 0.75] : [];

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="flex-shrink-0">
      <defs>
        <linearGradient id={`area-grad-${color.replace(/[^a-z0-9]/gi, "")}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.15" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      {/* Grid lines */}
      {gridLines.map((pct, i) => (
        <line
          key={i}
          x1={padding}
          y1={padding + chartH * (1 - pct)}
          x2={width - padding}
          y2={padding + chartH * (1 - pct)}
          stroke="var(--color-border)"
          strokeWidth="0.5"
          strokeDasharray="2 4"
        />
      ))}
      {/* Fill */}
      <path d={fillPath} fill={`url(#area-grad-${color.replace(/[^a-z0-9]/gi, "")})`} />
      {/* Line */}
      <path d={linePath} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      {/* End dot */}
      <circle cx={points[points.length - 1].x} cy={points[points.length - 1].y} r="2.5" fill={color} />
      <circle cx={points[points.length - 1].x} cy={points[points.length - 1].y} r="4" fill={color} opacity="0.2">
        <animate attributeName="r" values="4;7;4" dur="3s" repeatCount="indefinite" />
        <animate attributeName="opacity" values="0.2;0;0.2" dur="3s" repeatCount="indefinite" />
      </circle>
    </svg>
  );
}

/**
 * Status indicator with optional pulse.
 */
export function StatusDot({
  status,
  size = 6,
  pulse = false,
}: {
  status: "healthy" | "warning" | "error" | "unknown" | "idle";
  size?: number;
  pulse?: boolean;
}) {
  const colors: Record<string, string> = {
    healthy: "var(--color-success)",
    warning: "var(--color-warning)",
    error: "var(--color-error)",
    unknown: "var(--color-text-dim)",
    idle: "var(--color-border-hover)",
  };

  const color = colors[status] || colors.unknown;

  return (
    <svg width={size * 2} height={size * 2} viewBox={`0 0 ${size * 2} ${size * 2}`} className="flex-shrink-0">
      {pulse && (
        <circle cx={size} cy={size} r={size} fill={color} opacity="0.15">
          <animate attributeName="r" from={size * 0.6} to={size} dur="2s" repeatCount="indefinite" />
          <animate attributeName="opacity" from="0.3" to="0" dur="2s" repeatCount="indefinite" />
        </circle>
      )}
      <circle cx={size} cy={size} r={size * 0.4} fill={color} />
    </svg>
  );
}

/**
 * Responsive wrapper for AreaChart — fills container width automatically.
 */
export function ResponsiveAreaChart({
  values,
  height = 80,
  color = "var(--color-success)",
  showGrid = true,
}: {
  values: number[];
  height?: number;
  color?: string;
  showGrid?: boolean;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(400);

  useEffect(() => {
    if (!containerRef.current) return;
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setWidth(Math.floor(entry.contentRect.width));
      }
    });
    observer.observe(containerRef.current);
    setWidth(containerRef.current.offsetWidth);
    return () => observer.disconnect();
  }, []);

  return (
    <div ref={containerRef} className="w-full">
      {width > 0 && (
        <AreaChart values={values} width={width} height={height} color={color} showGrid={showGrid} />
      )}
    </div>
  );
}
