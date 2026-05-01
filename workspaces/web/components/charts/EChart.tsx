"use client";

import { useRef, useEffect } from "react";
import * as echarts from "echarts/core";
import { BarChart, LineChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
  GraphicComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { workspacesTheme } from "@/lib/echarts/theme";

echarts.use([
  BarChart,
  LineChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
  GraphicComponent,
  CanvasRenderer,
]);

const THEME_NAME = "workspaces";
let themeRegistered = false;
function ensureTheme() {
  if (!themeRegistered) {
    echarts.registerTheme(THEME_NAME, workspacesTheme);
    themeRegistered = true;
  }
}

interface EChartProps {
  option: Record<string, unknown>;
  height?: number;
}

export function EChart({ option, height = 320 }: EChartProps) {
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
    // option is rebuilt each render from server props; re-init on change
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (instanceRef.current) {
      instanceRef.current.setOption(option, { notMerge: true });
    }
  }, [option]);

  return <div ref={containerRef} style={{ width: "100%", height }} />;
}
