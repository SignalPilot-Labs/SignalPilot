import type { UseFormReturn } from "react-hook-form";
import { Checkbox } from "@/components/ui/checkbox";
import {
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { NativeSelect } from "@/components/ui/native-select";
import { NumberField } from "@/components/ui/number-field";
import type { UserConfig } from "@/core/config/config-schema";
import { getAppWidths } from "@/core/config/widths";
import { THEMES } from "@/theme/useTheme";
import { Kbd } from "@/components/ui/kbd";
import { formItemClasses, SettingGroup } from "../../common";
import { IsOverridden } from "../../is-overridden";
import { LOCALE_SYSTEM_VALUE } from "../constants";

interface DisplaySectionProps {
  form: UseFormReturn<UserConfig>;
  config: UserConfig;
  onSubmit: (values: UserConfig) => void;
}

export const DisplaySection: React.FC<DisplaySectionProps> = ({
  form,
  config,
  onSubmit,
}) => {
  return (
    <>
      <SettingGroup title="Display">
        <FormField
          control={form.control}
          name="display.default_width"
          render={({ field }) => (
            <div className="flex flex-col space-y-1">
              <FormItem className={formItemClasses}>
                <FormLabel>Default width</FormLabel>
                <FormControl>
                  <NativeSelect
                    data-testid="user-config-width-select"
                    onChange={(e) => field.onChange(e.target.value)}
                    value={field.value}
                    disabled={field.disabled}
                    className="inline-flex mr-2"
                  >
                    {getAppWidths().map((option) => (
                      <option value={option} key={option}>
                        {option}
                      </option>
                    ))}
                  </NativeSelect>
                </FormControl>
                <FormMessage />
                <IsOverridden
                  userConfig={config}
                  name="display.default_width"
                />
              </FormItem>

              <FormDescription>
                The default app width for new notebooks; overridden by
                "width" in the application config.
              </FormDescription>
            </div>
          )}
        />
        <FormField
          control={form.control}
          name="display.theme"
          render={({ field }) => (
            <div className="flex flex-col space-y-1">
              <FormItem className={formItemClasses}>
                <FormLabel>Theme</FormLabel>
                <FormControl>
                  <NativeSelect
                    data-testid="theme-select"
                    onChange={(e) => field.onChange(e.target.value)}
                    value={field.value}
                    disabled={field.disabled}
                    className="inline-flex mr-2"
                  >
                    {THEMES.map((option) => (
                      <option value={option} key={option}>
                        {option}
                      </option>
                    ))}
                  </NativeSelect>
                </FormControl>
                <FormMessage />
                <IsOverridden userConfig={config} name="display.theme" />
              </FormItem>

              <FormDescription>
                This theme will be applied to the user's configuration; it
                does not affect theme when sharing the notebook.
              </FormDescription>
            </div>
          )}
        />
        <FormField
          control={form.control}
          name="display.code_editor_font_size"
          render={({ field }) => (
            <FormItem className={formItemClasses}>
              <FormLabel>Code editor font size (px)</FormLabel>
              <FormControl>
                <span className="inline-flex mr-2">
                  <NumberField
                    aria-label="Code editor font size"
                    data-testid="code-editor-font-size-input"
                    className="m-0 w-24"
                    {...field}
                    value={field.value}
                    minValue={8}
                    maxValue={32}
                    onChange={(value) => {
                      field.onChange(value);
                      onSubmit(form.getValues());
                    }}
                  />
                </span>
              </FormControl>
              <FormMessage />
              <IsOverridden
                userConfig={config}
                name="display.code_editor_font_size"
              />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="display.locale"
          render={({ field }) => (
            <div className="flex flex-col space-y-1">
              <FormItem className={formItemClasses}>
                <FormLabel>Locale</FormLabel>
                <FormControl>
                  <NativeSelect
                    data-testid="locale-select"
                    onChange={(e) => {
                      if (e.target.value === LOCALE_SYSTEM_VALUE) {
                        field.onChange(undefined);
                      } else {
                        field.onChange(e.target.value);
                      }
                    }}
                    value={field.value || LOCALE_SYSTEM_VALUE}
                    disabled={field.disabled}
                    className="inline-flex mr-2"
                  >
                    <option value={LOCALE_SYSTEM_VALUE}>System</option>
                    {navigator.languages.map((option) => (
                      <option value={option} key={option}>
                        {option}
                      </option>
                    ))}
                  </NativeSelect>
                </FormControl>
                <FormMessage />
                <IsOverridden userConfig={config} name="display.locale" />
              </FormItem>

              <FormDescription>
                The locale to use for the notebook. If your desired locale
                is not listed, you can change it manually via{" "}
                <Kbd className="inline">sp config show</Kbd>.
              </FormDescription>
            </div>
          )}
        />
        <FormField
          control={form.control}
          name="display.reference_highlighting"
          render={({ field }) => (
            <div className="flex flex-col space-y-1">
              <FormItem className={formItemClasses}>
                <FormLabel>Reference highlighting</FormLabel>
                <FormControl>
                  <Checkbox
                    data-testid="reference-highlighting-checkbox"
                    checked={field.value}
                    onCheckedChange={field.onChange}
                  />
                </FormControl>
                <FormMessage />
                <IsOverridden
                  userConfig={config}
                  name="display.reference_highlighting"
                />
              </FormItem>

              <FormDescription>
                Visually emphasizes variables in a cell that are defined
                elsewhere in the notebook.
              </FormDescription>
            </div>
          )}
        />
      </SettingGroup>
      <SettingGroup title="Outputs">
        <FormField
          control={form.control}
          name="display.cell_output"
          render={({ field }) => (
            <div className="flex flex-col space-y-1">
              <FormItem className={formItemClasses}>
                <FormLabel>Cell output area</FormLabel>
                <FormControl>
                  <NativeSelect
                    data-testid="cell-output-select"
                    onChange={(e) => field.onChange(e.target.value)}
                    value={field.value}
                    disabled={field.disabled}
                    className="inline-flex mr-2"
                  >
                    {["above", "below"].map((option) => (
                      <option value={option} key={option}>
                        {option}
                      </option>
                    ))}
                  </NativeSelect>
                </FormControl>
                <FormMessage />
                <IsOverridden
                  userConfig={config}
                  name="display.cell_output"
                />
              </FormItem>

              <FormDescription>
                Where to display cell's output.
              </FormDescription>
            </div>
          )}
        />
      </SettingGroup>
    </>
  );
};
