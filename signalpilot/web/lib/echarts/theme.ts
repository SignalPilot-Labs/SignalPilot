export const signalpilotTheme = {
  color: ["#5B8FF9", "#5AD8A6", "#F6BD16", "#E86452", "#6DC8EC", "#945FB9"],
  backgroundColor: "transparent",
  textStyle: {
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
    color: "var(--color-text-dim)",
    fontSize: 11,
  },
  axisLine: {
    lineStyle: { color: "var(--color-border)" },
  },
  splitLine: {
    lineStyle: { color: "var(--color-border)", opacity: 0.4 },
  },
  tooltip: {
    backgroundColor: "var(--color-bg-card)",
    textStyle: { color: "var(--color-text)", fontSize: 11 },
    borderColor: "var(--color-border)",
    borderWidth: 1,
  },
  grid: {
    left: 48,
    right: 16,
    top: 24,
    bottom: 36,
    containLabel: true,
  },
  legend: {
    textStyle: { color: "var(--color-text-dim)", fontSize: 11 },
    icon: "rect",
  },
} as const;
