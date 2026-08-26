import { atom, useAtomValue } from "jotai";
import { resolvedSpConfigAtom } from "@/core/config/config";
import { store } from "@/core/state/jotai";

export type Theme = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

export const THEMES: Theme[] = ["light", "dark", "system"];

const themeAtom = atom((get) => {
  return get(resolvedSpConfigAtom).display.theme;
});

const prefersDarkModeAtom = atom(false);

function setupThemeListener(): void {
  if (typeof window === "undefined") {
    return;
  }
  if (!window.matchMedia) {
    return;
  }

  const media = window.matchMedia("(prefers-color-scheme: dark)");
  store.set(prefersDarkModeAtom, media.matches);
  media.addEventListener("change", (e) => {
    store.set(prefersDarkModeAtom, e.matches);
  });
}
setupThemeListener();

function getVsCodeTheme(): "light" | "dark" | undefined {
  // Guard for SSR / environments without DOM
  if (typeof document === "undefined") return undefined;
  const kind = document.body.dataset.vscodeThemeKind;
  switch (kind) {
    case "vscode-dark":
      return "dark";

    case "vscode-high-contrast":
      return "dark";

    case "vscode-light":
      return "light";

    // No default
  }
  return undefined;
}

const codeThemeAtom = atom<"light" | "dark" | undefined>(getVsCodeTheme());

function setupVsCodeThemeListener() {
  // Guard for SSR / environments without DOM
  if (typeof document === "undefined") return () => undefined;
  const observer = new MutationObserver(() => {
    const theme = getVsCodeTheme();
    store.set(codeThemeAtom, theme);
  });
  observer.observe(document.body, {
    attributes: true,
    attributeFilter: ["data-vscode-theme-kind"],
  });
  return () => observer.disconnect();
}
setupVsCodeThemeListener();

export const resolvedThemeAtom = atom((get) => {
  const theme = get(themeAtom);
  const codeTheme = get(codeThemeAtom);
  if (codeTheme !== undefined) {
    return codeTheme;
  }
  const prefersDarkMode = get(prefersDarkModeAtom);
  return theme === "system" ? (prefersDarkMode ? "dark" : "light") : theme;
});

/**
 * React hook to get the theme of the app.
 * This is stored in the user config.
 */
export function useTheme(): { theme: ResolvedTheme } {
  const theme = useAtomValue(resolvedThemeAtom, { store });
  return { theme };
}
