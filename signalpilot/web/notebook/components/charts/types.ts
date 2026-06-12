import type { SignalListenerHandler } from "vega-typings";

export interface SignalListener {
  signalName: string;
  handler: SignalListenerHandler;
}
