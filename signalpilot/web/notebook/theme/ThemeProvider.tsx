import { memo, type PropsWithChildren, useLayoutEffect } from "react";
import { useTheme } from "./useTheme";

/**
 * SignalPilot theme provider.
 *
 * Reactively adds/removes `${theme}` and `${theme}-theme` class tokens on
 * `document.body` and sets `document.body.dataset.theme` whenever the resolved
 * theme atom changes. Cleanup removes exactly what it added — no silent
 * defaults if `theme` is somehow undefined (upstream types guarantee it is
 * "light" | "dark").
 */
export const ThemeProvider: React.FC<PropsWithChildren> = memo(
  ({ children }) => {
    const { theme } = useTheme();
    useLayoutEffect(() => {
      document.body.classList.add(theme, `${theme}-theme`);
      document.body.dataset.theme = theme;
      return () => {
        document.body.classList.remove(theme, `${theme}-theme`);
        delete document.body.dataset.theme;
      };
    }, [theme]);

    return children;
  },
);
ThemeProvider.displayName = "ThemeProvider";

export const CssVariables: React.FC<{
  variables: Record<`--sp-${string}`, string>;
  children: React.ReactNode;
}> = ({ variables, children }) => {
  return (
    <div className="contents" style={variables}>
      {children}
    </div>
  );
};
