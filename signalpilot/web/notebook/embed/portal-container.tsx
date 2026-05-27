import React, {
  createContext,
  useCallback,
  useContext,
  type PropsWithChildren,
  type ReactElement,
} from "react";

export const EmbedPortalContext = createContext<HTMLElement | null>(null);

/**
 * Returns the embed-owned portal container, or null in standalone mode.
 * Callers pass null to Radix portal `container` props — Radix then falls
 * back to document.body, which is the correct standalone behavior.
 */
export function usePortalContainer(): HTMLElement | null {
  return useContext(EmbedPortalContext);
}

/**
 * Renders an in-tree div for Radix portals so they stay inside the embed
 * subtree rather than leaking to document.body. Only rendered inside embed
 * wrappers — standalone never mounts this provider.
 */
export function EmbedPortalProvider({
  children,
}: PropsWithChildren): ReactElement {
  const [container, setContainer] = React.useState<HTMLElement | null>(null);
  const setRef = useCallback((el: HTMLDivElement | null) => setContainer(el), []);

  return (
    <EmbedPortalContext.Provider value={container}>
      <div ref={setRef} data-sp-portal-root="" className="contents" />
      {children}
    </EmbedPortalContext.Provider>
  );
}
