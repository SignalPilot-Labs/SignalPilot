import type EChartsReactClass from "echarts-for-react";
import EChartsReact from "echarts-for-react";
import { forwardRef } from "react";

/**
 * Copied from Lightdash at e9830730ade4694774256ffc2fd880ce4963a57c.
 * See ../UPSTREAM.md and ../LICENSE.lightdash.
 */
const EChartsReactWrapper = forwardRef<
  EChartsReactClass,
  React.ComponentProps<typeof EChartsReactClass>
>((props, ref) => {
  return <EChartsReact {...props} ref={ref as never} />;
});

EChartsReactWrapper.displayName = "EChartsReactWrapper";

export default EChartsReactWrapper;

export type { default as EChartsReact } from "echarts-for-react";
export type {
  EChartsInstance,
  EChartsOption,
  EChartsReactProps,
} from "echarts-for-react";
