import React, { type JSX, lazy } from "react";
import { z } from "zod";
import type { IPlugin, IPluginProps } from "../types";

type T = [string, string];

interface Data {
  label: string | null;
  start: string;
  stop: string;
  step?: string;
  fullWidth: boolean;
  disabled?: boolean;
}

const LazyDateRange = lazy(() => import("./date/date-range-component"));

export class DateRangePickerPlugin implements IPlugin<T, Data> {
  tagName = "sp-date-range";

  validator = z.object({
    initialValue: z.tuple([z.string(), z.string()]),
    label: z.string().nullable(),
    start: z.string(),
    stop: z.string(),
    step: z.string().optional(),
    fullWidth: z.boolean().default(false),
    disabled: z.boolean().optional(),
  });

  render(props: IPluginProps<T, Data>): JSX.Element {
    return (
      <LazyDateRange
        {...props.data}
        value={props.value}
        setValue={props.setValue}
      />
    );
  }
}
