import { type CalendarDate, parseDate } from "@internationalized/date";
import type { JSX } from "react";
import { DateRangePicker } from "@/components/ui/date-picker";
import type { Setter } from "@/plugins/types";
import { Labeled } from "../common/labeled";

type T = [string, string];

interface Data {
  label: string | null;
  start: string;
  stop: string;
  step?: string;
  fullWidth: boolean;
  disabled?: boolean;
}

interface DateRangeProps extends Data {
  value: T;
  setValue: Setter<T>;
}

export default function DateRangeComponent(
  props: DateRangeProps,
): JSX.Element {
  const handleInput = (
    valueAsDateRange: {
      start: CalendarDate;
      end: CalendarDate;
    } | null,
  ) => {
    if (!valueAsDateRange) {
      return;
    }

    const { start, end } = valueAsDateRange;
    const isoStrRange: T = [start.toString(), end.toString()];
    props.setValue(isoStrRange);
  };

  return (
    <Labeled label={props.label} fullWidth={props.fullWidth}>
      <DateRangePicker
        granularity="day"
        value={{
          start: parseDate(props.value[0]),
          end: parseDate(props.value[1]),
        }}
        onChange={handleInput}
        aria-label={props.label ?? "date range picker"}
        minValue={parseDate(props.start)}
        maxValue={parseDate(props.stop)}
        isDisabled={props.disabled}
      />
    </Labeled>
  );
}
DateRangeComponent.displayName = "DateRangeComponent";
