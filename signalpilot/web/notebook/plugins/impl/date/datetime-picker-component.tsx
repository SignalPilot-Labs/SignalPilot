import { type CalendarDateTime, parseDateTime } from "@internationalized/date";
import type { JSX } from "react";
import { DatePicker } from "@/components/ui/date-picker";
import type { Setter } from "@/plugins/types";
import { Labeled } from "../common/labeled";

interface Data {
  label: string | null;
  start: string;
  stop: string;
  step?: string;
  precision: "hour" | "minute" | "second";
  fullWidth: boolean;
  disabled?: boolean;
}

interface DateTimePickerProps extends Data {
  value: string;
  setValue: Setter<string>;
}

export default function DateTimePickerComponent(
  props: DateTimePickerProps,
): JSX.Element {
  const handleInput = (valueAsDateTime: CalendarDateTime | null) => {
    if (!valueAsDateTime) {
      return;
    }

    const isoStr = valueAsDateTime.toString();
    props.setValue(isoStr);
  };

  const parsedValue = props.value ? parseDateTime(props.value) : undefined;

  return (
    <Labeled label={props.label} fullWidth={props.fullWidth}>
      <DatePicker
        granularity={props.precision}
        value={parsedValue}
        onChange={handleInput}
        aria-label={props.label ?? "date time picker"}
        minValue={parseDateTime(props.start)}
        maxValue={parseDateTime(props.stop)}
        isDisabled={props.disabled}
      />
    </Labeled>
  );
}
DateTimePickerComponent.displayName = "DateTimePickerComponent";
