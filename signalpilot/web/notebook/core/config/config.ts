import { atom, useAtom, useAtomValue, useSetAtom } from "jotai";
import { merge } from "lodash-es";
import { OverridingHotkeyProvider } from "../hotkeys/hotkeys";
import { type Platform, resolvePlatform } from "../hotkeys/shortcuts";
import { store } from "../state/jotai";
import {
  type AppConfig,
  defaultUserConfig,
  parseAppConfig,
  type UserConfig,
} from "./config-schema";

/**
 * Atom for storing the user config.
 */
export const userConfigAtom = atom<UserConfig>(defaultUserConfig());

export const configOverridesAtom = atom<{}>({});

export const resolvedSpConfigAtom = atom<UserConfig>((get) => {
  const overrides = get(configOverridesAtom);
  const userConfig = get(userConfigAtom);
  return merge({}, userConfig, overrides);
});

export const autoInstantiateAtom = atom((get) => {
  return get(resolvedSpConfigAtom).runtime.auto_instantiate;
});

export const hotkeyOverridesAtom = atom((get) => {
  return get(resolvedSpConfigAtom).keymap.overrides ?? {};
});

export const platformAtom = atom<Platform>(resolvePlatform());

export const hotkeysAtom = atom((get) => {
  const overrides = get(hotkeyOverridesAtom);
  const platform = get(platformAtom);
  return new OverridingHotkeyProvider(overrides, { platform });
});

export const autoSaveConfigAtom = atom((get) => {
  return get(resolvedSpConfigAtom).save;
});

export const aiAtom = atom((get) => {
  return get(resolvedSpConfigAtom).ai;
});

export const completionAtom = atom((get) => {
  return get(resolvedSpConfigAtom).completion;
});

export const keymapPresetAtom = atom((get) => {
  return get(resolvedSpConfigAtom).keymap.preset;
});

/**
 * Returns the user config.
 */
export function useUserConfig() {
  return useAtom(userConfigAtom);
}

export function useResolvedSpConfig() {
  return [
    useAtomValue(resolvedSpConfigAtom),
    useSetAtom(userConfigAtom),
  ] as const;
}

export function getResolvedSpConfig() {
  return store.get(resolvedSpConfigAtom);
}

export const aiEnabledAtom = atom<boolean>((get) => {
  return isAiEnabled(get(resolvedSpConfigAtom));
});

export const editorFontSizeAtom = atom<number>((get) => {
  return get(resolvedSpConfigAtom).display.code_editor_font_size;
});

export const localeAtom = atom<string | null | undefined>((get) => {
  return get(resolvedSpConfigAtom).display.locale;
});

export function isAiEnabled(config: UserConfig) {
  return (
    Boolean(config.ai?.models?.chat_model) ||
    Boolean(config.ai?.models?.edit_model) ||
    Boolean(config.ai?.models?.autocomplete_model)
  );
}

/**
 * Atom for storing the app config.
 */
export const appConfigAtom = atom<AppConfig>(parseAppConfig({}));

/**
 * Returns the app config.
 */
export function useAppConfig() {
  return useAtom(appConfigAtom);
}

export function useSetAppConfig() {
  return useSetAtom(appConfigAtom);
}

export function getAppConfig() {
  return store.get(appConfigAtom);
}

export const appWidthAtom = atom((get) => get(appConfigAtom).width);

export const disableFileDownloadsAtom = atom<boolean>((get) => {
  return get(resolvedSpConfigAtom).server?.disable_file_downloads ?? false;
});
