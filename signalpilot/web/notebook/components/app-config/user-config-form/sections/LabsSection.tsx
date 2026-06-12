import type { UseFormReturn } from "react-hook-form";
import { Checkbox } from "@/components/ui/checkbox";
import {
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
} from "@/components/ui/form";
import type { UserConfig } from "@/core/config/config-schema";
import { formItemClasses, SettingGroup } from "../../common";

interface LabsSectionProps {
  form: UseFormReturn<UserConfig>;
}

export const LabsSection: React.FC<LabsSectionProps> = ({ form }) => {
  return (
    <SettingGroup title="Experimental Features">
      <p className="text-sm text-muted-secondary mb-4">
        ⚠️ These features are experimental and may require restarting your
        notebook to take effect.
      </p>

      <FormField
        control={form.control}
        name="experimental.rtc_v2"
        render={({ field }) => (
          <div className="flex flex-col gap-y-1">
            <FormItem className={formItemClasses}>
              <FormLabel className="font-normal">
                Real-Time Collaboration
              </FormLabel>
              <FormControl>
                <Checkbox
                  data-testid="rtc-checkbox"
                  checked={field.value === true}
                  onCheckedChange={field.onChange}
                />
              </FormControl>
            </FormItem>

            <FormDescription>
              Enable experimental real-time collaboration. This change
              requires a page refresh to take effect.
            </FormDescription>
          </div>
        )}
      />
    </SettingGroup>
  );
};
