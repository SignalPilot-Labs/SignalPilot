/* oxlint-disable typescript/no-explicit-any */

import type { AnyWidget } from "@anywidget/types";
import { type JSX, useEffect, useRef } from "react";
import { useAsyncData } from "@/hooks/useAsyncData";
import type { HTMLElementNotDerivedFromRef } from "@/hooks/useEventListener";
import type { IPluginProps } from "@/plugins/types";
import { prettyError } from "@/utils/errors";
import { Logger } from "@/utils/Logger";
import { ErrorBanner } from "../common/error-banner";
import { MODEL_MANAGER, type Model } from "./model";
import type { ModelState, WidgetModelId } from "./types";
import { BINDING_MANAGER, WIDGET_DEF_REGISTRY } from "./widget-binding";

interface Data {
  jsUrl: string;
  jsHash: string;
  modelId: WidgetModelId;
}

type AnyWidgetState = ModelState;

interface ModelIdRef {
  model_id?: WidgetModelId;
}

export function useAnyWidgetModule(opts: { jsUrl: string; jsHash: string }) {
  const { jsUrl, jsHash } = opts;

  const {
    data: jsModule,
    error,
    refetch,
  } = useAsyncData(async () => {
    return await WIDGET_DEF_REGISTRY.getModule(jsUrl, jsHash);
  }, [jsHash]);

  const hasError = Boolean(error);
  useEffect(() => {
    if (hasError && jsUrl) {
      WIDGET_DEF_REGISTRY.invalidate(jsHash);
      refetch();
    }
  }, [hasError, jsUrl]);

  return {
    jsModule,
    error,
  };
}

export function useMountCss(css: string | null | undefined, host: HTMLElement) {
  useEffect(() => {
    const shadowRoot = host.shadowRoot;
    if (!css || !shadowRoot) {
      return;
    }

    if (
      "adoptedStyleSheets" in Document.prototype &&
      "replace" in CSSStyleSheet.prototype
    ) {
      const sheet = new CSSStyleSheet();
      try {
        sheet.replaceSync(css);
        if (shadowRoot) {
          shadowRoot.adoptedStyleSheets = [
            ...shadowRoot.adoptedStyleSheets,
            sheet,
          ];
        }
        return () => {
          if (shadowRoot) {
            shadowRoot.adoptedStyleSheets =
              shadowRoot.adoptedStyleSheets.filter((s) => s !== sheet);
          }
        };
      } catch {
        // Fall through to inline styles if constructed sheets fail
      }
    }

    const style = document.createElement("style");
    style.innerHTML = css;
    shadowRoot.append(style);
    return () => {
      style.remove();
    };
  }, [css, host]);
}

async function runAnyWidgetModule<T extends AnyWidgetState>(
  widgetDef: AnyWidget<T>,
  model: Model<T>,
  modelId: WidgetModelId,
  el: HTMLElement,
  signal: AbortSignal,
): Promise<void> {
  el.innerHTML = "";

  try {
    const binding = BINDING_MANAGER.getOrCreate(modelId);
    const render = await binding.bind(widgetDef, model);
    await render(el, signal);
  } catch (error) {
    Logger.error("Error rendering anywidget", error);
    el.classList.add("text-error");
    el.innerHTML = `Error rendering anywidget: ${prettyError(error)}`;
  }
}

function isAnyWidgetModule(mod: any): mod is { default: AnyWidget } {
  if (!mod.default) {
    return false;
  }

  return (
    typeof mod.default === "function" ||
    typeof mod.default?.render === "function" ||
    typeof mod.default?.initialize === "function"
  );
}

interface LoadedSlotProps<T extends AnyWidgetState> {
  widget: AnyWidget<T>;
  modelId: WidgetModelId;
  host: HTMLElementNotDerivedFromRef;
}

const LoadedSlot = <T extends AnyWidgetState>({
  widget,
  modelId,
  host,
}: LoadedSlotProps<T> & { widget: AnyWidget<T> }) => {
  const htmlRef = useRef<HTMLDivElement>(null);

  const model = MODEL_MANAGER.getSync(modelId);

  if (!model) {
    Logger.error("Model not found for modelId", modelId);
  }

  const css = model?.get("_css");
  useMountCss(css, host);

  useEffect(() => {
    if (!htmlRef.current || !model) {
      return;
    }
    const controller = new AbortController();
    runAnyWidgetModule(
      widget,
      model,
      modelId,
      htmlRef.current,
      controller.signal,
    );
    return () => controller.abort();
  }, [widget, modelId, model]);

  return <div ref={htmlRef} />;
};

export default function AnyWidgetComponent(
  props: IPluginProps<ModelIdRef, Data>,
): JSX.Element {
  const { jsUrl, jsHash, modelId } = props.data;
  const host = props.host as HTMLElementNotDerivedFromRef;

  const { jsModule, error } = useAnyWidgetModule({ jsUrl, jsHash });

  if (error) {
    return <ErrorBanner error={error} />;
  }

  if (!jsModule) {
    return <></>;
  }

  if (!isAnyWidgetModule(jsModule)) {
    const err = new Error(
      `Module at ${jsUrl} does not appear to be a valid anywidget`,
    );
    return <ErrorBanner error={err} />;
  }

  return (
    <LoadedSlot
      key={`${jsHash}:${modelId}`}
      widget={jsModule.default}
      modelId={modelId}
      host={host}
    />
  );
}
AnyWidgetComponent.displayName = "AnyWidgetComponent";

export const visibleForTesting = {
  LoadedSlot,
  runAnyWidgetModule,
  isAnyWidgetModule,
};
