import React, { type JSX, lazy } from "react";
import { z } from "zod";
import type { IPlugin, IPluginProps } from "../types";

type T = number[];

interface Data {
  start: number;
  stop: number;
  step?: number;
  label: string | null;
  steps: T | null;
  debounce: boolean;
  orientation: "horizontal" | "vertical";
  showValue: boolean;
  fullWidth: boolean;
  disabled?: boolean;
}

const LazyRangeSlider = lazy(() => import("./slider/range-slider-component"));

export class RangeSliderPlugin implements IPlugin<T, Data> {
  tagName = "sp-range-slider";

  validator = z.object({
    initialValue: z.array(z.number()),
    label: z.string().nullable(),
    start: z.number(),
    stop: z.number(),
    step: z.number().optional(),
    steps: z.array(z.number()).nullable(),
    debounce: z.boolean().default(false),
    orientation: z.enum(["horizontal", "vertical"]).default("horizontal"),
    showValue: z.boolean().default(false),
    fullWidth: z.boolean().default(false),
    disabled: z.boolean().optional(),
  });

  render(props: IPluginProps<T, Data>): JSX.Element {
    return (
      <LazyRangeSlider
        {...props.data}
        value={props.value}
        setValue={props.setValue}
      />
    );
  }
}
