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
import type { UserConfig } from "@/core/config/config-schema";
import { ExternalLink } from "@/components/ui/links";
import { formItemClasses, SettingGroup } from "../../common";
import { IsOverridden } from "../../is-overridden";

interface RuntimeSectionProps {
  form: UseFormReturn<UserConfig>;
  config: UserConfig;
}

export const RuntimeSection: React.FC<RuntimeSectionProps> = ({
  form,
  config,
}) => {
  return (
    <SettingGroup title="Runtime configuration">
      <FormField
        control={form.control}
        name="runtime.auto_instantiate"
        render={({ field }) => (
          <div className="flex flex-col gap-y-1">
            <FormItem className={formItemClasses}>
              <FormLabel className="font-normal">
                Autorun on startup
              </FormLabel>
              <FormControl>
                <Checkbox
                  data-testid="auto-instantiate-checkbox"
                  disabled={field.disabled}
                  checked={field.value}
                  onCheckedChange={field.onChange}
                />
              </FormControl>
              <FormMessage />
              <IsOverridden
                userConfig={config}
                name="runtime.auto_instantiate"
              />
            </FormItem>

            <FormDescription>
              Whether to automatically run all cells on startup.
            </FormDescription>
          </div>
        )}
      />
      <FormField
        control={form.control}
        name="runtime.on_cell_change"
        render={({ field }) => (
          <div className="flex flex-col gap-y-1">
            <FormItem className={formItemClasses}>
              <FormLabel className="font-normal">
                On cell change
              </FormLabel>
              <FormControl>
                <NativeSelect
                  data-testid="on-cell-change-select"
                  onChange={(e) => field.onChange(e.target.value)}
                  value={field.value}
                  className="inline-flex mr-2"
                >
                  {["lazy", "autorun"].map((option) => (
                    <option value={option} key={option}>
                      {option}
                    </option>
                  ))}
                </NativeSelect>
              </FormControl>
              <FormMessage />
              <IsOverridden
                userConfig={config}
                name="runtime.on_cell_change"
              />
            </FormItem>
            <FormDescription>
              Whether SignalPilot should automatically run cells or just mark
              them as stale. If "autorun", SignalPilot will automatically run
              affected cells when a cell is run or a UI element is
              interacted with; if "lazy", SignalPilot will mark affected cells
              as stale but won't re-run them.
            </FormDescription>
          </div>
        )}
      />
      <FormField
        control={form.control}
        name="runtime.auto_reload"
        render={({ field }) => (
          <div className="flex flex-col gap-y-1">
            <FormItem className={formItemClasses}>
              <FormLabel className="font-normal">
                On module change
              </FormLabel>
              <FormControl>
                <NativeSelect
                  data-testid="auto-reload-select"
                  onChange={(e) => field.onChange(e.target.value)}
                  value={field.value}
                  className="inline-flex mr-2"
                >
                  {["off", "lazy", "autorun"].map((option) => (
                    <option value={option} key={option}>
                      {option}
                    </option>
                  ))}
                </NativeSelect>
              </FormControl>
              <FormMessage />
              <IsOverridden
                userConfig={config}
                name="runtime.auto_reload"
              />
            </FormItem>
            <FormDescription>
              Whether SignalPilot should automatically reload modules before
              executing cells. If "lazy", SignalPilot will mark cells affected
              by module modifications as stale; if "autorun", affected
              cells will be automatically re-run.
            </FormDescription>
          </div>
        )}
      />

      <FormField
        control={form.control}
        name="runtime.reactive_tests"
        render={({ field }) => (
          <div className="flex flex-col gap-y-1">
            <FormItem className={formItemClasses}>
              <FormLabel className="font-normal">
                Autorun Unit Tests
              </FormLabel>
              <FormControl>
                <Checkbox
                  data-testid="reactive-test-checkbox"
                  checked={field.value}
                  onCheckedChange={field.onChange}
                />
              </FormControl>
            </FormItem>
            <IsOverridden
              userConfig={config}
              name="runtime.reactive_tests"
            />
            <FormMessage />
            <FormDescription>
              Enable reactive pytest tests in notebook. When a cell
              contains only test functions (test_*) and classes (Test_*),
              SignalPilot will automatically run them with pytest (requires
              notebook restart).
            </FormDescription>{" "}
          </div>
        )}
      />

      <FormDescription>
        Learn more in the{" "}
        <ExternalLink href="https://docs.signalpilot.ai/docs/">
          docs
        </ExternalLink>
        .
      </FormDescription>
    </SettingGroup>
  );
};
