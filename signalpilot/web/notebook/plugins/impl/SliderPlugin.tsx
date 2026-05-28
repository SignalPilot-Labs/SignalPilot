import React, { type JSX, lazy } from "react";
import { z } from "zod";
import type { IPlugin, IPluginProps } from "../types";

type T = number;

interface Data {
  start: T;
  stop: T;
  step?: T;
  label: string | null;
  steps: T[] | null;
  debounce: boolean;
  orientation: "horizontal" | "vertical";
  showValue: boolean;
  fullWidth: boolean;
  includeInput: boolean;
  disabled?: boolean;
}

const LazySlider = lazy(() => import("./slider/slider-component"));

export class SliderPlugin implements IPlugin<T, Data> {
  tagName = "sp-slider";

  validator = z.object({
    initialValue: z.number(),
    label: z.string().nullable(),
    start: z.number(),
    stop: z.number(),
    step: z.number().optional(),
    steps: z.array(z.number()).nullable(),
    debounce: z.boolean().default(false),
    orientation: z.enum(["horizontal", "vertical"]).default("horizontal"),
    showValue: z.boolean().default(false),
    fullWidth: z.boolean().default(false),
    includeInput: z.boolean().default(false),
    disabled: z.boolean().optional(),
  });

  render(props: IPluginProps<T, Data>): JSX.Element {
    return (
      <LazySlider
        {...props.data}
        value={props.value}
        setValue={props.setValue}
      />
    );
  }
}
