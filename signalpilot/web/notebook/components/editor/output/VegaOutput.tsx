import { Suspense } from "react";
import type { VisualizationSpec } from "vega-embed";
import { LazyVegaEmbed } from "@/components/charts/lazy";
import { tooltipHandler } from "@/components/charts/tooltip";
import { useTheme } from "@/theme/useTheme";
import { ChartLoadingState } from "../../data-table/charts/components/chart-states";

type ContainerWidth = number | "container";

interface VegaOutputProps {
  spec: unknown;
}

export default function VegaOutput({ spec }: VegaOutputProps) {
  const { theme } = useTheme();

  return (
    <Suspense fallback={<ChartLoadingState />}>
      <LazyVegaEmbed
        spec={spec as VisualizationSpec | string}
        data-container-width={getContainerWidth(spec)}
        options={{
          theme: theme === "dark" ? "dark" : undefined,
          mode: "vega-lite",
          tooltip: tooltipHandler.call,
          renderer: "canvas",
        }}
      />
    </Suspense>
  );
}

function getContainerWidth(spec: unknown): ContainerWidth | undefined {
  if (typeof spec !== "object" || spec === null) {
    return undefined;
  }
  if ("width" in spec) {
    return spec.width as ContainerWidth | undefined;
  }
  if ("spec" in spec) {
    return getContainerWidth(spec.spec);
  }
  return undefined;
}
