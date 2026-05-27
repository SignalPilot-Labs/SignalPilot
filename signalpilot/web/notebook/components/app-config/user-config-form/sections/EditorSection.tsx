import { AlertTriangleIcon } from "lucide-react";
import type { UseFormReturn } from "react-hook-form";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
import { NumberField } from "@/components/ui/number-field";
import { KEYMAP_PRESETS } from "@/core/codemirror/keymaps/keymaps";
import type { UserConfig } from "@/core/config/config-schema";
import type { Capabilities } from "@/core/kernel/messages";
import { Banner } from "@/plugins/impl/common/error-banner";
import { arrayToggle } from "@/utils/arrays";
import { Badge } from "@/components/ui/badge";
import { ExternalLink } from "@/components/ui/links";
import { Tooltip } from "@/components/ui/tooltip";
import { formItemClasses, SettingGroup } from "../../common";
import { IsOverridden } from "../../is-overridden";

interface EditorSectionProps {
  form: UseFormReturn<UserConfig>;
  config: UserConfig;
  capabilities: Capabilities;
  acceptOnEnter: boolean;
  setAcceptOnEnter: (value: boolean) => void;
  setKeyboardShortcutsOpen: (value: boolean) => void;
  onSubmit: (values: UserConfig) => void;
  htmlCheckboxId: string;
  ipynbCheckboxId: string;
}

export const EditorSection: React.FC<EditorSectionProps> = ({
  form,
  config,
  capabilities,
  acceptOnEnter,
  setAcceptOnEnter,
  setKeyboardShortcutsOpen,
  onSubmit,
  htmlCheckboxId,
  ipynbCheckboxId,
}) => {
  return (
    <>
      <SettingGroup title="Autosave">
        <FormField
          control={form.control}
          name="save.autosave"
          render={({ field }) => (
            <FormItem className={formItemClasses}>
              <FormLabel className="font-normal">
                Autosave enabled
              </FormLabel>
              <FormControl>
                <Checkbox
                  data-testid="autosave-checkbox"
                  checked={field.value === "after_delay"}
                  disabled={field.disabled}
                  onCheckedChange={(checked) => {
                    field.onChange(checked ? "after_delay" : "off");
                  }}
                />
              </FormControl>
              <FormMessage />
              <IsOverridden userConfig={config} name="save.autosave" />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="save.autosave_delay"
          render={({ field }) => (
            <FormItem className={formItemClasses}>
              <FormLabel>Autosave delay (seconds)</FormLabel>
              <FormControl>
                <NumberField
                  aria-label="Autosave delay"
                  data-testid="autosave-delay-input"
                  className="m-0 w-24"
                  isDisabled={
                    form.getValues("save.autosave") !== "after_delay"
                  }
                  {...field}
                  value={field.value / 1000}
                  minValue={1}
                  onChange={(value) => {
                    field.onChange(value * 1000);
                    if (!Number.isNaN(value)) {
                      onSubmit(form.getValues());
                    }
                  }}
                />
              </FormControl>
              <FormMessage />
              <IsOverridden
                userConfig={config}
                name="save.autosave_delay"
              />
            </FormItem>
          )}
        />
        {/* auto_download is a runtime setting in the backend, but it makes
         * more sense as an autosave setting. */}
        <FormField
          control={form.control}
          name="runtime.default_auto_download"
          render={({ field }) => (
            <div className="flex flex-col gap-y-1">
              <FormItem className={formItemClasses}>
                <FormLabel>Save cell outputs as</FormLabel>
                <FormControl>
                  <div className="flex gap-4">
                    <div className="flex items-center space-x-2">
                      <Checkbox
                        id={htmlCheckboxId}
                        checked={
                          Array.isArray(field.value) &&
                          field.value.includes("html")
                        }
                        onCheckedChange={() => {
                          const currentValue = Array.isArray(field.value)
                            ? field.value
                            : [];
                          field.onChange(
                            arrayToggle(currentValue, "html"),
                          );
                        }}
                      />
                      <FormLabel htmlFor={htmlCheckboxId}>HTML</FormLabel>
                    </div>
                    <div className="flex items-center space-x-2">
                      <Checkbox
                        id={ipynbCheckboxId}
                        checked={
                          Array.isArray(field.value) &&
                          field.value.includes("ipynb")
                        }
                        onCheckedChange={() => {
                          const currentValue = Array.isArray(field.value)
                            ? field.value
                            : [];
                          field.onChange(
                            arrayToggle(currentValue, "ipynb"),
                          );
                        }}
                      />
                      <FormLabel htmlFor={ipynbCheckboxId}>
                        IPYNB
                      </FormLabel>
                    </div>
                  </div>
                </FormControl>
                <FormMessage />
                <IsOverridden
                  userConfig={config}
                  name="runtime.default_auto_download"
                />
              </FormItem>
              <FormDescription>
                When enabled, SignalPilot will periodically save notebooks in
                your selected formats (HTML, IPYNB) to a folder named{" "}
                <Kbd className="inline">__sp__</Kbd> next to your
                notebook file.
              </FormDescription>
            </div>
          )}
        />
      </SettingGroup>
      <SettingGroup title="Formatting">
        <FormField
          control={form.control}
          name="save.format_on_save"
          render={({ field }) => (
            <FormItem className={formItemClasses}>
              <FormLabel className="font-normal">
                Format on save
              </FormLabel>
              <FormControl>
                <Checkbox
                  data-testid="format-on-save-checkbox"
                  checked={field.value}
                  disabled={field.disabled}
                  onCheckedChange={(checked) => {
                    field.onChange(checked);
                  }}
                />
              </FormControl>
              <FormMessage />
              <IsOverridden
                userConfig={config}
                name="save.format_on_save"
              />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="formatting.line_length"
          render={({ field }) => (
            <div className="flex flex-col space-y-1">
              <FormItem className={formItemClasses}>
                <FormLabel>Line length</FormLabel>
                <FormControl>
                  <NumberField
                    aria-label="Line length"
                    data-testid="line-length-input"
                    className="m-0 w-24"
                    {...field}
                    value={field.value}
                    minValue={1}
                    maxValue={1000}
                    onChange={(value) => {
                      // Ignore NaN
                      field.onChange(value);
                      if (!Number.isNaN(value)) {
                        onSubmit(form.getValues());
                      }
                    }}
                  />
                </FormControl>
                <FormMessage />
                <IsOverridden
                  userConfig={config}
                  name="formatting.line_length"
                />
              </FormItem>

              <FormDescription>
                Maximum line length when formatting code.
              </FormDescription>
            </div>
          )}
        />
      </SettingGroup>
      <SettingGroup title="Autocomplete">
        <FormField
          control={form.control}
          name="completion.activate_on_typing"
          render={({ field }) => (
            <div className="flex flex-col space-y-1">
              <FormItem className={formItemClasses}>
                <FormLabel className="font-normal">
                  Autocomplete
                </FormLabel>
                <FormControl>
                  <Checkbox
                    data-testid="autocomplete-checkbox"
                    checked={field.value}
                    disabled={field.disabled}
                    onCheckedChange={(checked) => {
                      field.onChange(Boolean(checked));
                    }}
                  />
                </FormControl>
                <FormMessage />
                <IsOverridden
                  userConfig={config}
                  name="completion.activate_on_typing"
                />
              </FormItem>
              <FormDescription>
                When unchecked, code completion is still available through
                a hotkey.
              </FormDescription>

            </div>
          )}
        />
        <div className="flex flex-col space-y-1">
          <FormItem className={formItemClasses}>
            <FormLabel className="font-normal">
              Accept suggestion on Enter
            </FormLabel>
            <FormControl>
              <Checkbox
                data-testid="accept-completion-on-enter-checkbox"
                checked={acceptOnEnter}
                onCheckedChange={(checked) =>
                  setAcceptOnEnter(Boolean(checked))
                }
              />
            </FormControl>
          </FormItem>
          <FormDescription>
            When unchecked, pressing Enter inserts a new line instead of
            accepting an autocomplete suggestion. Use Tab to accept
            suggestions.
          </FormDescription>
        </div>
        <FormField
          control={form.control}
          name="completion.signature_hint_on_typing"
          render={({ field }) => (
            <div className="flex flex-col space-y-1">
              <FormItem className={formItemClasses}>
                <FormLabel className="font-normal">
                  Signature hints
                </FormLabel>
                <FormControl>
                  <Checkbox
                    data-testid="signature-hint-on-type-checkbox"
                    checked={field.value ?? false}
                    disabled={field.disabled}
                    onCheckedChange={(checked) => {
                      field.onChange(Boolean(checked));
                    }}
                  />
                </FormControl>
                <FormMessage />
                <IsOverridden
                  userConfig={config}
                  name="completion.signature_hint_on_typing"
                />
              </FormItem>
              <FormDescription>
                Display signature hints while typing within function
                calls.
              </FormDescription>
            </div>
          )}
        />
      </SettingGroup>
      <SettingGroup title="Language Servers">
        <FormDescription>
          See the{" "}
          <ExternalLink href="https://docs.signalpilot.ai/docs/">
            docs
          </ExternalLink>{" "}
          for more information about language server support.
        </FormDescription>
        <FormDescription>
          <strong>Note:</strong> When using multiple language servers,
          different features may conflict.
        </FormDescription>

        <FormField
          control={form.control}
          name="language_servers.pylsp.enabled"
          render={({ field }) => (
            <div className="flex flex-col gap-1">
              <FormItem className={formItemClasses}>
                <FormLabel>
                  <Badge variant="defaultOutline" className="mr-2">
                    Beta
                  </Badge>
                  Python Language Server (
                  <ExternalLink href="https://github.com/python-lsp/python-lsp-server">
                    docs
                  </ExternalLink>
                  )
                </FormLabel>
                <FormControl>
                  <Checkbox
                    data-testid="pylsp-checkbox"
                    checked={field.value}
                    disabled={field.disabled}
                    onCheckedChange={(checked) => {
                      field.onChange(Boolean(checked));
                    }}
                  />
                </FormControl>
                <FormMessage />
                <IsOverridden
                  userConfig={config}
                  name="language_servers.pylsp.enabled"
                />
              </FormItem>
              {field.value && !capabilities.pylsp && (
                <Banner kind="danger">
                  The Python Language Server is not available in your
                  current environment. Please install{" "}
                  <Kbd className="inline">python-lsp-server</Kbd> in your
                  environment.
                </Banner>
              )}
            </div>
          )}
        />
        <FormField
          control={form.control}
          name="language_servers.basedpyright.enabled"
          render={({ field }) => (
            <div className="flex flex-col gap-1">
              <FormItem className={formItemClasses}>
                <FormLabel>
                  <Badge variant="defaultOutline" className="mr-2">
                    Beta
                  </Badge>
                  basedpyright (
                  <ExternalLink href="https://github.com/DetachHead/basedpyright">
                    docs
                  </ExternalLink>
                  )
                </FormLabel>
                <FormControl>
                  <Checkbox
                    data-testid="basedpyright-checkbox"
                    checked={field.value}
                    disabled={field.disabled}
                    onCheckedChange={(checked) => {
                      field.onChange(Boolean(checked));
                    }}
                  />
                </FormControl>
                <FormMessage />
                <IsOverridden
                  userConfig={config}
                  name="language_servers.basedpyright.enabled"
                />
              </FormItem>
              {field.value && !capabilities.basedpyright && (
                <Banner kind="danger">
                  basedpyright is not available in your current
                  environment. Please install{" "}
                  <Kbd className="inline">basedpyright</Kbd> in your
                  environment.
                </Banner>
              )}
            </div>
          )}
        />
        <FormField
          control={form.control}
          name="language_servers.pyrefly.enabled"
          render={({ field }) => (
            <div className="flex flex-col gap-1">
              <FormItem className={formItemClasses}>
                <FormLabel>
                  <Badge variant="defaultOutline" className="mr-2">
                    Beta
                  </Badge>
                  Pyrefly (
                  <ExternalLink href="https://github.com/facebook/pyrefly">
                    docs
                  </ExternalLink>
                  )
                </FormLabel>
                <FormControl>
                  <Checkbox
                    data-testid="pyrefly-checkbox"
                    checked={field.value}
                    disabled={field.disabled}
                    onCheckedChange={(checked) => {
                      field.onChange(Boolean(checked));
                    }}
                  />
                </FormControl>
                <FormMessage />
                <IsOverridden
                  userConfig={config}
                  name="language_servers.pyrefly.enabled"
                />
              </FormItem>
              {field.value && !capabilities.pyrefly && (
                <Banner kind="danger">
                  Pyrefly is not available in your current environment.
                  Please install <Kbd className="inline">pyrefly</Kbd> in
                  your environment.
                </Banner>
              )}
            </div>
          )}
        />
        <FormField
          control={form.control}
          name="language_servers.ty.enabled"
          render={({ field }) => (
            <div className="flex flex-col gap-1">
              <FormItem className={formItemClasses}>
                <FormLabel>
                  <Badge variant="defaultOutline" className="mr-2">
                    Beta
                  </Badge>
                  ty (
                  <ExternalLink href="https://github.com/astral-sh/ty">
                    docs
                  </ExternalLink>
                  )
                </FormLabel>
                <FormControl>
                  <Checkbox
                    data-testid="ty-checkbox"
                    checked={field.value}
                    disabled={field.disabled}
                    onCheckedChange={(checked) => {
                      field.onChange(Boolean(checked));
                    }}
                  />
                </FormControl>
                <FormMessage />
                <IsOverridden
                  userConfig={config}
                  name="language_servers.ty.enabled"
                />
              </FormItem>
              {field.value && !capabilities.ty && (
                <Banner kind="danger">
                  ty is not available in your current environment. Please
                  install <Kbd className="inline">ty</Kbd> in your
                  environment.
                </Banner>
              )}
            </div>
          )}
        />
        <FormField
          control={form.control}
          name="diagnostics.enabled"
          render={({ field }) => (
            <FormItem className={formItemClasses}>
              <FormLabel>
                <Badge variant="defaultOutline" className="mr-2">
                  Beta
                </Badge>
                Diagnostics
              </FormLabel>
              <FormControl>
                <Checkbox
                  data-testid="diagnostics-checkbox"
                  checked={field.value}
                  disabled={field.disabled}
                  onCheckedChange={(checked) => {
                    field.onChange(Boolean(checked));
                  }}
                />
              </FormControl>
              <FormMessage />
              <IsOverridden
                userConfig={config}
                name="diagnostics.enabled"
              />
            </FormItem>
          )}
        />
      </SettingGroup>

      <SettingGroup title="Keymap">
        <FormField
          control={form.control}
          name="keymap.preset"
          render={({ field }) => (
            <div className="flex flex-col space-y-1">
              <FormItem className={formItemClasses}>
                <FormLabel>Keymap</FormLabel>
                <FormControl>
                  <NativeSelect
                    data-testid="keymap-select"
                    onChange={(e) => field.onChange(e.target.value)}
                    value={field.value}
                    disabled={field.disabled}
                    className="inline-flex mr-2"
                  >
                    {KEYMAP_PRESETS.map((option) => (
                      <option value={option} key={option}>
                        {option}
                      </option>
                    ))}
                  </NativeSelect>
                </FormControl>
                <FormMessage />
                <IsOverridden userConfig={config} name="keymap.preset" />
              </FormItem>
            </div>
          )}
        />
        <FormField
          control={form.control}
          name="keymap.destructive_delete"
          render={({ field }) => (
            <div className="flex flex-col space-y-1">
              <FormItem className={formItemClasses}>
                <FormLabel className="font-normal">
                  Destructive delete
                </FormLabel>
                <FormControl>
                  <Checkbox
                    data-testid="destructive-delete-checkbox"
                    checked={field.value}
                    disabled={field.disabled}
                    onCheckedChange={(checked) => {
                      field.onChange(Boolean(checked));
                    }}
                  />
                </FormControl>
                <FormMessage />
                <IsOverridden
                  userConfig={config}
                  name="keymap.destructive_delete"
                />
              </FormItem>
              <FormDescription className="flex items-center gap-1">
                Allow deleting non-empty cells
                <Tooltip
                  content={
                    <div className="max-w-xs">
                      <strong>Use with caution:</strong> Deleting cells
                      with code can lose work and computed results since
                      variables are removed from memory.
                    </div>
                  }
                >
                  <AlertTriangleIcon className="w-3 h-3 text-(--amber-11)" />
                </Tooltip>
              </FormDescription>

              <div>
                <Button
                  variant="link"
                  className="mb-0 px-0"
                  type="button"
                  onClick={(evt) => {
                    evt.preventDefault();
                    evt.stopPropagation();
                    setKeyboardShortcutsOpen(true);
                  }}
                >
                  Edit Keyboard Shortcuts
                </Button>
              </div>
            </div>
          )}
        />
      </SettingGroup>
    </>
  );
};
