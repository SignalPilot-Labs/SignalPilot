export const workspacesTheme = {
  color: ["#5B8FF9", "#5AD8A6", "#F6BD16", "#E86452", "#6DC8EC", "#945FB9"],
  backgroundColor: "transparent",
  textStyle: {
    fontFamily: 'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
    color: "#1F2937",
  },
  axisLine: {
    lineStyle: {
      color: "#E5E7EB",
    },
  },
  splitLine: {
    lineStyle: {
      color: "#F3F4F6",
    },
  },
  tooltip: {
    backgroundColor: "#0F172A",
    textStyle: {
      color: "#F8FAFC",
    },
    borderRadius: 8,
  },
  grid: {
    left: 48,
    right: 16,
    top: 24,
    bottom: 36,
    containLabel: true,
  },
  legend: {
    textStyle: {
      color: "#374151",
    },
    icon: "circle",
  },
} as const;
