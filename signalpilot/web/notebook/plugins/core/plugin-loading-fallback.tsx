import React from "react";
import { Spinner } from "@/components/icons/spinner";

const DEFAULT_MIN_HEIGHT = 200;

interface PluginLoadingFallbackProps {
  host: HTMLElement;
}

/**
 * Suspense fallback for lazy-loaded plugin components.
 *
 * Derives `minHeight` from the host element's current bounding box so that
 * tall renderers (Plotly, DataFrame) don't collapse to zero height while the
 * dynamic chunk is loading — which would cause layout shift when the real
 * component mounts.
 *
 * Falls back to DEFAULT_MIN_HEIGHT (200 px) when the host has no height yet
 * (first render before layout paint).
 */
export function PluginLoadingFallback({
  host,
}: PluginLoadingFallbackProps): React.ReactElement {
  const rect = host.getBoundingClientRect();
  const minHeight = rect.height > 0 ? rect.height : DEFAULT_MIN_HEIGHT;

  return (
    <div
      style={{ minHeight }}
      className="flex items-center justify-center"
      aria-busy="true"
      aria-label="Loading plugin"
    >
      <Spinner size="medium" centered={true} />
    </div>
  );
}
