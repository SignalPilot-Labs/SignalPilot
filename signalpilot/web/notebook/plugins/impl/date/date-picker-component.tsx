import { type CalendarDate, parseDate } from "@internationalized/date";
import type { JSX } from "react";
import { DatePicker } from "@/components/ui/date-picker";
import type { Setter } from "@/plugins/types";
import { Labeled } from "../common/labeled";

interface Data {
  label: string | null;
  start: string;
  stop: string;
  step?: string;
  fullWidth: boolean;
  disabled?: boolean;
}

interface DatePickerProps extends Data {
  value: string;
  setValue: Setter<string>;
}

export default function DatePickerComponent(
  props: DatePickerProps,
): JSX.Element {
  const handleInput = (valueAsDate: CalendarDate | null) => {
    if (!valueAsDate) {
      return;
    }

    const isoStr = valueAsDate.toString();
    props.setValue(isoStr);
  };

  return (
    <Labeled label={props.label} fullWidth={props.fullWidth}>
      <DatePicker
        granularity="day"
        value={parseDate(props.value)}
        onChange={handleInput}
        aria-label={props.label ?? "date picker"}
        minValue={parseDate(props.start)}
        maxValue={parseDate(props.stop)}
        isDisabled={props.disabled}
      />
    </Labeled>
  );
}
DatePickerComponent.displayName = "DatePickerComponent";
