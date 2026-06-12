import type * as Plotly from "plotly.js";
import { z } from "zod";
import type { IPlugin, IPluginProps, Setter } from "@/plugins/types";
import type { Figure } from "./Plot";
import React, { type JSX, lazy } from "react";

type T =
  | {
      points?: Record<string, unknown>[] | Plotly.PlotDatum[];
      indices?: number[];
      range?: {
        x?: number[];
        y?: number[];
      };
      lasso?: {
        x?: unknown[];
        y?: unknown[];
      };
      selections?: unknown[];
      dragmode?: Plotly.Layout["dragmode"];
      xaxis?: Partial<Plotly.LayoutAxis>;
      yaxis?: Partial<Plotly.LayoutAxis>;
    }
  | undefined;

interface Data {
  figure: Figure;
  config: Partial<Plotly.Config>;
}

export interface PlotlyPluginProps extends Data {
  value: T;
  setValue: Setter<T>;
  host: HTMLElement;
}

const LazyPlotlyComponent = lazy(() => import("./plotly-component"));

export class PlotlyPlugin implements IPlugin<T, Data> {
  tagName = "sp-plotly";

  validator = z.object({
    figure: z
      .object({})
      .passthrough()
      .transform((spec) => spec as unknown as Figure),
    config: z.object({}).passthrough(),
  });

  render(props: IPluginProps<T, Data>): JSX.Element {
    return (
      <LazyPlotlyComponent
        {...props.data}
        host={props.host}
        value={props.value}
        setValue={props.setValue}
      />
    );
  }
}
