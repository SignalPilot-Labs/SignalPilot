import { type JSX, useEffect, useId, useState } from "react";
import { useLocale } from "react-aria";
import { NumberField } from "@/components/ui/number-field";
import { Slider } from "@/components/ui/slider";
import { cn } from "@/utils/cn";
import { prettyScientificNumber } from "@/utils/numbers";
import { Labeled } from "../common/labeled";

export interface SliderProps {
  value: number;
  setValue: (value: number | ((prev: number) => number)) => void;
  label: string | null;
  start: number;
  stop: number;
  step?: number;
  steps: number[] | null;
  debounce: boolean;
  orientation: "horizontal" | "vertical";
  showValue: boolean;
  fullWidth: boolean;
  includeInput: boolean;
  disabled?: boolean;
}

export default function SliderComponent(props: SliderProps): JSX.Element {
  const {
    label,
    setValue,
    value,
    start,
    stop,
    step,
    steps,
    debounce,
    orientation,
    showValue,
    fullWidth,
    includeInput,
    disabled,
  } = props;

  const id = useId();
  const { locale } = useLocale();

  const valueMap = (sliderValue: number): number => {
    if (steps && steps.length > 0) {
      return steps[sliderValue];
    }
    return sliderValue;
  };

  const [internalValue, setInternalValue] = useState(value);
  useEffect(() => {
    setInternalValue(value);
  }, [value]);

  const sliderElement = (
    <Labeled
      label={label}
      id={id}
      align={orientation === "horizontal" ? "left" : "top"}
      fullWidth={fullWidth}
      className={cn(fullWidth && "my-1 w-full")}
    >
      <div
        className={cn(
          "flex items-center gap-2",
          orientation === "vertical" &&
            "items-end inline-flex justify-center self-center mx-2",
        )}
      >
        <Slider
          id={id}
          className={cn(
            "relative flex items-center select-none",
            !fullWidth && "data-[orientation=horizontal]:w-36 ",
            "data-[orientation=vertical]:h-36",
          )}
          value={[internalValue]}
          min={start}
          max={stop}
          step={step}
          orientation={orientation}
          onValueChange={([nextValue]) => {
            setInternalValue(nextValue);
            if (!debounce) {
              setValue(nextValue);
            }
          }}
          onValueCommit={([nextValue]) => {
            if (debounce) {
              setValue(nextValue);
            }
          }}
          valueMap={valueMap}
          disabled={disabled}
        />
        {showValue && (
          <div className="text-xs text-muted-foreground min-w-[16px]">
            {prettyScientificNumber(valueMap(internalValue), { locale })}
          </div>
        )}
        {includeInput && (
          <NumberField
            value={valueMap(internalValue)}
            onChange={(nextValue) => {
              if (nextValue == null || Number.isNaN(nextValue)) {
                nextValue = Number(start);
              }
              setInternalValue(nextValue);
              setValue(nextValue);
            }}
            minValue={start}
            maxValue={stop}
            step={step}
            className="w-24"
            aria-label={`${label || "Slider"} value input`}
            isDisabled={disabled}
          />
        )}
      </div>
    </Labeled>
  );

  return sliderElement;
}

SliderComponent.displayName = "SliderComponent";
