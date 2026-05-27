import type { TooltipHandler } from "vega-typings";
import { Handler } from "vega-tooltip";

// Create the tooltip handler at module-init time when running in a browser.
// The vega-tooltip `Handler` constructor accesses `document`, so it must not
// be called in SSR / Node contexts.
//
// None of the four consumers (Output.tsx, lazy-chart.tsx, vega-component.tsx,
// ConnectedDataExplorerComponent.tsx) carry a "use client" directive, so SSR
// reachability cannot be ruled out. Per spec-review binding instruction: when
// `handler` is null (SSR), `.call` is a no-op rather than a throw.
const handler: Handler | null =
  typeof document !== "undefined" ? new Handler() : null;

// Expose only the `.call` property that consumers use.
// The `Handler` class's `call` method is a `TooltipHandler` function.
// In SSR contexts handler is null and `.call` is a no-op that returns nothing.
const noopCall: TooltipHandler = () => {
  // no-op: tooltips are not rendered in SSR contexts
};

export const tooltipHandler: { call: TooltipHandler } = {
  get call() {
    return handler !== null ? handler.call : noopCall;
  },
};
