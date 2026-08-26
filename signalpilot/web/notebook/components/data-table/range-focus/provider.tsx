import { Provider, createStore } from "jotai";
import { useRef } from "react";

export const CellSelectionProvider = ({
  children,
}: {
  children: React.ReactNode;
}) => {
  // Each table gets its own store so cell selection state is isolated
  // without needing jotai-scope (which requires buildStore-compatible stores).
  const storeRef = useRef(createStore());
  return <Provider store={storeRef.current}>{children}</Provider>;
};
