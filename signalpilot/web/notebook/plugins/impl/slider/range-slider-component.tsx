import { dequal as isEqual } from "dequal";
import { type JSX, useEffect, useId, useState } from "react";
import { useLocale } from "react-aria";
import { RangeSlider } from "@/components/ui/range-slider";
import { cn } from "@/utils/cn";
import { prettyScientificNumber } from "@/utils/numbers";
import { Labeled } from "../common/labeled";

export interface RangeSliderProps {
  value: number[];
  setValue: (value: number[] | ((prev: number[]) => number[])) => void;
  label: string | null;
  start: number;
  stop: number;
  step?: number;
  steps: number[] | null;
  debounce: boolean;
  orientation: "horizontal" | "vertical";
  showValue: boolean;
  fullWidth: boolean;
  disabled?: boolean;
}

export default function RangeSliderComponent(
  props: RangeSliderProps,
): JSX.Element {
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
      className={cn(fullWidth && "my-1 w-full")}
      fullWidth={fullWidth}
    >
      <div
        className={cn(
          "flex items-center gap-2",
          orientation === "vertical" &&
            "items-end inline-flex justify-center self-center mx-2",
          fullWidth && "w-full",
        )}
      >
        <RangeSlider
          id={id}
          className={cn(
            "relative flex items-center select-none",
            !fullWidth && "data-[orientation=horizontal]:w-36 ",
            "data-[orientation=vertical]:h-36",
          )}
          value={internalValue}
          min={start}
          max={stop}
          step={step}
          orientation={orientation}
          disabled={disabled}
          onValueChange={(nextValue: number[]) => {
            setInternalValue(nextValue);
            if (!debounce) {
              setValue(nextValue);
            }
          }}
          onValueCommit={(nextValue: number[]) => {
            if (debounce) {
              setValue(nextValue);
            }
          }}
          onPointerUp={() => {
            if (debounce && !isEqual(internalValue, value)) {
              setValue(internalValue);
            }
          }}
          onMouseUp={() => {
            if (debounce && !isEqual(internalValue, value)) {
              setValue(internalValue);
            }
          }}
          valueMap={valueMap}
        />
        {showValue && (
          <div className="text-xs text-muted-foreground min-w-[16px]">
            {`${prettyScientificNumber(valueMap(internalValue[0]), {
              locale,
            })}, ${prettyScientificNumber(valueMap(internalValue[1]), { locale })}`}
          </div>
        )}
      </div>
    </Labeled>
  );

  return sliderElement;
}

RangeSliderComponent.displayName = "RangeSliderComponent";
