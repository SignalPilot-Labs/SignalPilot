"use client";

import { useRef, useEffect } from "react";
import * as echarts from "echarts/core";
import { BarChart, LineChart, PieChart, ScatterChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
  GraphicComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { signalpilotTheme } from "@/lib/echarts/theme";

echarts.use([
  BarChart,
  LineChart,
  PieChart,
  ScatterChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
  GraphicComponent,
  CanvasRenderer,
]);

const THEME_NAME = "signalpilot";
let themeRegistered = false;
function ensureTheme() {
  if (!themeRegistered) {
    echarts.registerTheme(THEME_NAME, signalpilotTheme);
    themeRegistered = true;
  }
}

interface EChartProps {
  option: Record<string, unknown>;
  ariaLabel: string;
  height?: number;
}

export function EChart({ option, ariaLabel, height = 320 }: EChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    ensureTheme();
    const container = containerRef.current;
    if (!container) return;

    const instance = echarts.init(container, THEME_NAME);
    instanceRef.current = instance;
    instance.setOption(option);

    const observer = new ResizeObserver(() => {
      instance.resize();
    });
    observer.observe(container);

    return () => {
      observer.disconnect();
      instance.dispose();
      instanceRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (instanceRef.current) {
      instanceRef.current.setOption(option, { notMerge: true });
    }
  }, [option]);

  return <div ref={containerRef} role="img" aria-label={ariaLabel} style={{ width: "100%", height }} />;
}
