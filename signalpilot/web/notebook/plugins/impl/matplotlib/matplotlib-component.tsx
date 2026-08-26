import { type JSX, useEffect, useRef } from "react";
import {
  MatplotlibRenderer,
  type MatplotlibState,
} from "./matplotlib-renderer";

export default function MatplotlibComponent(props: MatplotlibState): JSX.Element {
  const ref = useRef<HTMLDivElement>(null);
  const instance = useRef<MatplotlibRenderer | null>(null);

  useEffect(() => {
    const container = ref.current;
    if (!container) {
      return;
    }
    const controller = new AbortController();
    instance.current = new MatplotlibRenderer(container, {
      state: props,
      signal: controller.signal,
    });
    return () => {
      controller.abort();
      instance.current = null;
    };
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // No dependency array: intentionally syncs all props into the imperative
  // renderer after every render. The renderer's update() method diffs internally.
  useEffect(() => {
    instance.current?.update(props);
  });

  return <div ref={ref} />;
}
MatplotlibComponent.displayName = "MatplotlibComponent";
