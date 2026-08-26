import React, { type JSX, lazy } from "react";
import { z } from "zod";
import type { IPlugin, IPluginProps } from "../types";

type T = string;

interface Data {
  label: string | null;
  start: string;
  stop: string;
  step?: string;
  fullWidth: boolean;
  disabled?: boolean;
}

const LazyDatePicker = lazy(() => import("./date/date-picker-component"));

export class DatePickerPlugin implements IPlugin<T, Data> {
  tagName = "sp-date";

  validator = z.object({
    initialValue: z.string(),
    label: z.string().nullable(),
    start: z.string(),
    stop: z.string(),
    step: z.string().optional(),
    fullWidth: z.boolean().default(false),
    disabled: z.boolean().optional(),
  });

  render(props: IPluginProps<T, Data>): JSX.Element {
    return (
      <LazyDatePicker
        {...props.data}
        value={props.value}
        setValue={props.setValue}
        disabled={props.data.disabled}
      />
    );
  }
}
