import { zodResolver } from "@hookform/resolvers/zod";
import { useAtom, useAtomValue, useSetAtom } from "jotai";
import { merge } from "lodash-es";
import React, { useId, useRef } from "react";
import { useLocale } from "react-aria";
import { useForm } from "react-hook-form";
import type z from "zod";
import { acceptCompletionOnEnterAtom } from "@/core/codemirror/completion/accept-on-enter-atom";
import { Form } from "@/components/ui/form";
import { Kbd } from "@/components/ui/kbd";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { capabilitiesAtom } from "@/core/config/capabilities";
import type { Capabilities } from "@/core/kernel/messages";
import { useUserConfig } from "@/core/config/config";
import {
  type UserConfig,
  UserConfigSchema,
} from "@/core/config/config-schema";
import { spVersionAtom } from "@/core/meta/state";
import { viewStateAtom } from "@/core/mode";
import { useRequestClient } from "@/core/network/requests";
import { useDebouncedCallback } from "@/hooks/useDebounce";
import { cn } from "@/utils/cn";
import { keyboardShortcutsAtom } from "../../editor/controls/keyboard-shortcuts";
import { OptionalFeatures } from "../optional-features";
import { applyManualInjections, getDirtyValues } from "../get-dirty-values";
import { activeUserConfigCategoryAtom, categories } from "./atoms";
import type { SettingCategoryId } from "./atoms";
import { FORM_DEBOUNCE } from "./constants";
import { EditorSection } from "./sections/EditorSection";
import { DisplaySection } from "./sections/DisplaySection";
import { PackagesAndDataSection } from "./sections/PackagesAndDataSection";
import { RuntimeSection } from "./sections/RuntimeSection";
import { LabsSection } from "./sections/LabsSection";

export const UserConfigForm: React.FC = () => {
  const [config, setConfig] = useUserConfig();
  const [acceptOnEnter, setAcceptOnEnter] = useAtom(
    acceptCompletionOnEnterAtom,
  );
  const formElement = useRef<HTMLFormElement>(null);
  const setKeyboardShortcutsOpen = useSetAtom(keyboardShortcutsAtom);
  const [activeCategory, setActiveCategory] = useAtom(
    activeUserConfigCategoryAtom,
  );

  let capabilities: Capabilities = useAtomValue(capabilitiesAtom);
  const isHome = useAtomValue(viewStateAtom).mode === "home";
  // The home page does not fetch kernel capabilities, so we just turn them all on
  if (isHome) {
    capabilities = {
      terminal: true,
      pylsp: true,
      ty: true,
      basedpyright: true,
      pyrefly: true,
    };
  }

  const spVersion = useAtomValue(spVersionAtom);
  const { locale } = useLocale();
  const { saveUserConfig } = useRequestClient();

  // Create form
  const form = useForm({
    resolver: zodResolver(
      UserConfigSchema as unknown as z.ZodType<unknown, UserConfig>,
    ),
    defaultValues: config,
  });

  const onSubmitNotDebounced = async (values: UserConfig) => {
    // Only send values that were actually changed to avoid
    // overwriting backend values the form doesn't manage
    const dirtyValues = getDirtyValues(values, form.formState.dirtyFields);
    applyManualInjections({
      values,
      dirtyValues,
      touchedFields: form.formState.touchedFields,
    });
    if (Object.keys(dirtyValues).length === 0) {
      return; // Nothing changed
    }

    await saveUserConfig({ config: dirtyValues });
    // Only apply the changed keys; this avoids stale request responses
    // overwriting newer config changes.
    setConfig((prev) => merge({}, prev, dirtyValues));
  };
  const onSubmit = useDebouncedCallback(onSubmitNotDebounced, FORM_DEBOUNCE);

  const htmlCheckboxId = useId();
  const ipynbCheckboxId = useId();

  const renderBody = () => {
    switch (activeCategory) {
      case "editor":
        return (
          <EditorSection
            form={form}
            config={config}
            capabilities={capabilities}
            acceptOnEnter={acceptOnEnter}
            setAcceptOnEnter={setAcceptOnEnter}
            setKeyboardShortcutsOpen={setKeyboardShortcutsOpen}
            onSubmit={onSubmit}
            htmlCheckboxId={htmlCheckboxId}
            ipynbCheckboxId={ipynbCheckboxId}
          />
        );
      case "display":
        return (
          <DisplaySection
            form={form}
            config={config}
            onSubmit={onSubmit}
          />
        );
      case "packageManagementAndData":
        return (
          <PackagesAndDataSection
            form={form}
            config={config}
            onSubmit={onSubmit}
          />
        );
      case "runtime":
        return (
          <RuntimeSection
            form={form}
            config={config}
          />
        );
      case "optionalDeps":
        return <OptionalFeatures />;
      case "labs":
        return (
          <LabsSection form={form} />
        );
    }
  };

  const configMessage = (
    <p className="text-muted-secondary">
      User configuration is stored in <Kbd className="inline">sp.toml</Kbd>
      <br />
      Run <Kbd className="inline">sp config show</Kbd> in your terminal to
      show your current configuration and file location.
    </p>
  );

  return (
    <Form {...form}>
      <form
        ref={formElement}
        onChange={form.handleSubmit(onSubmit)}
        className="flex text-pretty overflow-hidden"
      >
        <Tabs
          value={activeCategory}
          onValueChange={(value) =>
            setActiveCategory(value as SettingCategoryId)
          }
          orientation="vertical"
          className="w-1/3 border-r h-full overflow-auto p-3"
        >
          <TabsList className="self-start max-h-none flex flex-col gap-2 shrink-0 bg-background flex-1 min-h-full">
            {categories.map((category) => (
              <TabsTrigger
                key={category.id}
                value={category.id}
                className="w-full text-left p-2 data-[state=active]:bg-primary data-[state=active]:text-primary-foreground justify-start"
              >
                <div className="flex gap-4 items-center text-lg overflow-hidden">
                  <span
                    className={cn(
                      category.className,
                      "w-8 h-8 rounded flex items-center justify-center text-muted-foreground shrink-0",
                    )}
                  >
                    <category.Icon className="w-4 h-4" />
                  </span>
                  <span className="truncate">{category.label}</span>
                </div>
              </TabsTrigger>
            ))}

            <div className="p-2 text-xs text-muted-foreground self-start flex flex-col gap-1">
              <span>Version: {spVersion}</span>
              <span>Locale: {locale}</span>
            </div>

            <div className="flex-1" />
            {configMessage}
          </TabsList>
        </Tabs>
        <div className="w-2/3 pl-6 gap-2 flex flex-col overflow-auto p-6">
          {renderBody()}
        </div>
      </form>
    </Form>
  );
};
