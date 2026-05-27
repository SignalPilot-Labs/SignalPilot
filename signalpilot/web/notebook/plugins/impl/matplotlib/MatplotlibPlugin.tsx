import React, { lazy } from "react";
import { z } from "zod";
import type { IPlugin, IPluginProps } from "@/plugins/types";
import type {
  Data,
  SelectionValue as T,
} from "./matplotlib-renderer";

const LazyMatplotlibComponent = lazy(() => import("./matplotlib-component"));

export class MatplotlibPlugin implements IPlugin<T, Data> {
  tagName = "sp-matplotlib";

  validator = z.object({
    chartBase64: z.string(),
    xBounds: z.tuple([z.number(), z.number()]),
    yBounds: z.tuple([z.number(), z.number()]),
    axesPixelBounds: z.tuple([z.number(), z.number(), z.number(), z.number()]),
    width: z.number(),
    height: z.number(),
    selectionColor: z.string().default("#3b82f6"),
    selectionOpacity: z.number().default(0.15),
    strokeWidth: z.number().default(2),
    debounce: z.boolean(),
    xScale: z.enum(["linear", "log"]).default("linear"),
    yScale: z.enum(["linear", "log"]).default("linear"),
  });

  render(props: IPluginProps<T, Data>): React.JSX.Element {
    return (
      <LazyMatplotlibComponent
        {...props.data}
        value={props.value}
        setValue={props.setValue}
      />
    );
  }
}
