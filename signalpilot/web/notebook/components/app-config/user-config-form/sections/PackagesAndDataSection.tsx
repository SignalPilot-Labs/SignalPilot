import type { UseFormReturn } from "react-hook-form";
import {
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Kbd } from "@/components/ui/kbd";
import { NativeSelect } from "@/components/ui/native-select";
import {
  PackageManagerNames,
  type UserConfig,
} from "@/core/config/config-schema";
import { ExternalLink } from "@/components/ui/links";
import { formItemClasses, SettingGroup } from "../../common";
import { DataForm } from "../../data-form";
import { IsOverridden } from "../../is-overridden";

interface PackagesAndDataSectionProps {
  form: UseFormReturn<UserConfig>;
  config: UserConfig;
  onSubmit: (values: UserConfig) => void;
}

export const PackagesAndDataSection: React.FC<PackagesAndDataSectionProps> = ({
  form,
  config,
  onSubmit,
}) => {
  return (
    <>
      <SettingGroup title="Package Management">
        <FormField
          control={form.control}
          name="package_management.manager"
          render={({ field }) => (
            <div className="flex flex-col space-y-1">
              <FormItem className={formItemClasses}>
                <FormLabel>Manager</FormLabel>
                <FormControl>
                  <NativeSelect
                    data-testid="package-manager-select"
                    onChange={(e) => field.onChange(e.target.value)}
                    value={field.value}
                    disabled={field.disabled}
                    className="inline-flex mr-2"
                  >
                    {PackageManagerNames.map((option) => (
                      <option value={option} key={option}>
                        {option}
                      </option>
                    ))}
                  </NativeSelect>
                </FormControl>
                <FormMessage />
                <IsOverridden
                  userConfig={config}
                  name="package_management.manager"
                />
              </FormItem>

              <FormDescription>
                When SignalPilot comes across a module that is not installed,
                you will be prompted to install it using your preferred
                package manager. Learn more in the{" "}
                <ExternalLink href="https://docs.signalpilot.ai/docs/">
                  docs
                </ExternalLink>
                .
                <br />
                <br />
                Running SignalPilot in a{" "}
                <ExternalLink href="https://docs.signalpilot.ai/docs/">
                  sandboxed environment
                </ExternalLink>{" "}
                is only supported by <Kbd className="inline">uv</Kbd>
              </FormDescription>
            </div>
          )}
        />
      </SettingGroup>
      <SettingGroup title="Data">
        <DataForm form={form} config={config} onSubmit={onSubmit} />
      </SettingGroup>
    </>
  );
};
