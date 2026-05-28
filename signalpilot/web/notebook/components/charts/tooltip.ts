import type { TooltipHandler } from "vega-typings";
import { Handler } from "vega-tooltip";

// Lazily create the tooltip handler so that the vega-tooltip `Handler`
// constructor (which accesses `document`) is not called at module-init time.
// This allows the module to be imported in SSR/Node contexts without crashing.
let _handler: Handler | null = null;
function getHandler(): Handler {
  if (!_handler) {
    _handler = new Handler();
  }
  return _handler;
}

// Expose only the `.call` property that consumers use.
// The `Handler` class's `call` method is a `TooltipHandler` function.
export const tooltipHandler: { call: TooltipHandler } = {
  get call() {
    return getHandler().call;
  },
};
