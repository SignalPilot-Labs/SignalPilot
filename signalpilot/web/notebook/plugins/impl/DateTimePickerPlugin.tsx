import React, { type JSX, lazy } from "react";
import { z } from "zod";
import type { IPlugin, IPluginProps } from "../types";

type T = string;

interface Data {
  label: string | null;
  start: string;
  stop: string;
  step?: string;
  precision: "hour" | "minute" | "second";
  fullWidth: boolean;
  disabled?: boolean;
}

const LazyDateTimePicker = lazy(
  () => import("./date/datetime-picker-component"),
);

export class DateTimePickerPlugin implements IPlugin<T, Data> {
  tagName = "sp-datetime";

  validator = z.object({
    initialValue: z.string(),
    label: z.string().nullable(),
    start: z.string(),
    stop: z.string(),
    step: z.string().optional(),
    precision: z.enum(["hour", "minute", "second"]).default("minute"),
    fullWidth: z.boolean().default(false),
    disabled: z.boolean().optional(),
  });

  render(props: IPluginProps<T, Data>): JSX.Element {
    return (
      <LazyDateTimePicker
        {...props.data}
        value={props.value}
        setValue={props.setValue}
      />
    );
  }
}
