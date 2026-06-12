/* oxlint-disable typescript/no-explicit-any */

import { type JSX, useCallback, useEffect, useRef } from "react";
import { useEventListener } from "@/hooks/useEventListener";
import { isTrustedVirtualFileUrl } from "@/plugins/core/trusted-url";
import { MODEL_MANAGER, type Model } from "@/plugins/impl/anywidget/model";
import type { ModelState, WidgetModelId } from "@/plugins/impl/anywidget/types";
import type { IPluginProps } from "@/plugins/types";
import { downloadBlob } from "@/utils/download";
import { Logger } from "@/utils/Logger";
import { Functions } from "@/utils/functions";
import { MplCommWebSocket } from "./mpl-websocket-shim";

const MPL_SCOPE_CLASS = "mpl-interactive-figure";

interface Data {
  mplJsUrl: string;
  cssUrl: string;
  toolbarImages: Record<string, string>;
  width: number;
  height: number;
}

interface ModelIdRef {
  model_id: WidgetModelId;
}

declare global {
  interface Window {
    mpl: {
      figure: new (
        id: string,
        ws: MplCommWebSocket,
        ondownload: (figure: MplFigure, format: string) => void,
        element: HTMLElement,
      ) => MplFigure;
      toolbar_items: [
        string | null,
        string | null,
        string | null,
        string | null,
      ][];
    };
  }
}

interface MplFigure {
  id: string;
  ws: MplCommWebSocket;
  root: HTMLElement;
  send_message: (type: string, properties: Record<string, unknown>) => void;
}

let mplJsLoading: Promise<void> | null = null;

async function ensureMplJs(jsUrl: string): Promise<void> {
  if (window.mpl) {
    return;
  }
  if (!isTrustedVirtualFileUrl(jsUrl)) {
    throw new Error(
      `Refusing to load mpl.js from untrusted URL: ${String(jsUrl)}`,
    );
  }
  if (mplJsLoading) {
    return mplJsLoading;
  }
  mplJsLoading = new Promise<void>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = jsUrl;
    script.onload = () => resolve();
    script.onerror = () => {
      mplJsLoading = null;
      reject(new Error("Failed to load mpl.js"));
    };
    document.head.append(script);
  });
  return mplJsLoading;
}

function patchToolbarImages(
  container: HTMLElement,
  toolbarImages: Record<string, string>,
): () => void {
  const patchImg = (img: HTMLImageElement) => {
    const src = img.getAttribute("src") || "";
    const match = src.match(/_images\/(.+)\.png$/);
    if (match) {
      const name = match[1];
      const dataUri = toolbarImages[name];
      if (dataUri) {
        img.src = dataUri;
      }
    }
    const srcset = img.getAttribute("srcset") || "";
    const srcsetMatch = srcset.match(/_images\/(.+)\.png\s+2x$/);
    if (srcsetMatch) {
      const name = srcsetMatch[1];
      const dataUri = toolbarImages[name];
      if (dataUri) {
        img.srcset = `${dataUri} 2x`;
      }
    }
  };

  for (const img of container.querySelectorAll("img")) {
    patchImg(img);
  }

  const observer = new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      for (const node of mutation.addedNodes) {
        if (node instanceof HTMLImageElement) {
          patchImg(node);
        } else if (node instanceof HTMLElement) {
          for (const img of node.querySelectorAll("img")) {
            patchImg(img);
          }
        }
      }
    }
  });

  observer.observe(container, { childList: true, subtree: true });
  return () => observer.disconnect();
}

function injectCss(container: HTMLElement, cssUrl: string): () => void {
  if (!isTrustedVirtualFileUrl(cssUrl)) {
    Logger.error(
      `Refusing to load mpl CSS from untrusted URL: ${String(cssUrl)}`,
    );
    return Functions.NOOP;
  }
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = cssUrl;
  container.append(link);
  return () => link.remove();
}

export default function MplInteractiveComponent(
  props: IPluginProps<ModelIdRef, Data>,
): JSX.Element {
  const { mplJsUrl, cssUrl, toolbarImages, width, height } = props.data;
  const { model_id: modelId } = props.value;
  const containerRef = useRef<HTMLDivElement>(null);
  const figureRef = useRef<MplFigure | null>(null);
  const wsRef = useRef<MplCommWebSocket | null>(null);

  const setupFigure = useCallback(
    async (container: HTMLElement) => {
      await ensureMplJs(mplJsUrl);

      if (!window.mpl) {
        Logger.error("mpl.js failed to load");
        return;
      }

      let model: Model<ModelState>;
      try {
        model = await MODEL_MANAGER.get(modelId);
      } catch {
        Logger.error("Failed to get model for mpl interactive", modelId);
        return;
      }

      const fakeWs = new MplCommWebSocket((msg: unknown) => {
        model.send(msg);
      });
      wsRef.current = fakeWs;

      const handleCustomMessage = (
        content: { type: string; data?: unknown; format?: string },
        buffers?: readonly DataView[],
      ) => {
        if (!content) {
          return;
        }

        if (content.type === "json") {
          fakeWs.receiveJson(content.data);
        } else if (content.type === "binary" && buffers && buffers.length > 0) {
          fakeWs.receiveBinary(buffers[0]);
        } else if (
          content.type === "download" &&
          buffers &&
          buffers.length > 0
        ) {
          const fmt = content.format || "png";
          const dv = buffers[0];
          const ab = dv.buffer.slice(
            dv.byteOffset,
            dv.byteOffset + dv.byteLength,
          ) as ArrayBuffer;
          downloadBlob(
            new Blob([ab], { type: `image/${fmt}` }),
            `figure.${fmt}`,
          );
        }
      };

      model.on("msg:custom", handleCustomMessage as any);

      const figId = modelId;
      const ondownload = (_figure: MplFigure, format: string) => {
        model.send({ type: "download", format });
      };

      const fig = new window.mpl.figure(figId, fakeWs, ondownload, container);
      figureRef.current = fig;

      const canvasDiv = fig.root.querySelector<HTMLElement>("div[tabindex]");
      if (canvasDiv) {
        canvasDiv.style.width = `${width}px`;
        canvasDiv.style.height = `${height}px`;
      }

      setTimeout(() => {
        fakeWs.onopen?.();
      }, 0);

      return () => {
        model.off("msg:custom", handleCustomMessage as any);
        fakeWs.close();
      };
    },
    [modelId, mplJsUrl, width, height],
  );

  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }

    container.innerHTML = "";

    const removeCss = injectCss(container, cssUrl);
    const removeImageObserver = patchToolbarImages(container, toolbarImages);

    let cleanup: (() => void) | undefined;
    let cancelled = false;

    setupFigure(container)
      .then((cleanupFn) => {
        if (cancelled) {
          cleanupFn?.();
          return;
        }
        cleanup = cleanupFn;
      })
      .catch((error) => {
        if (!cancelled) {
          Logger.error("Failed to set up MPL interactive figure", error);
        }
      });

    return () => {
      cancelled = true;
      removeCss();
      removeImageObserver();
      cleanup?.();
      container.innerHTML = "";
    };
  }, [modelId, cssUrl, toolbarImages, setupFigure]);

  useEventListener(document, "visibilitychange", () => {
    const fig = figureRef.current;
    if (!document.hidden && fig?.ws?.readyState === WebSocket.OPEN) {
      fig.send_message("refresh", {});
    }
  });

  return <div ref={containerRef} className={MPL_SCOPE_CLASS} />;
}
MplInteractiveComponent.displayName = "MplInteractiveComponent";

export const visibleForTesting = {
  ensureMplJs,
  injectCss,
  resetMplJsLoading: () => {
    mplJsLoading = null;
  },
};
