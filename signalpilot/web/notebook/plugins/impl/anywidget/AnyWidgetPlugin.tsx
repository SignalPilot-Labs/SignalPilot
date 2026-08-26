import React, { lazy } from "react";
import { z } from "zod";
import { createPlugin } from "@/plugins/core/builder";
import type { WidgetModelId } from "./types";

/**
 * Value payload sent by the frontend on state updates.
 */
interface ModelIdRef {
  model_id?: WidgetModelId;
}

const LazyAnyWidgetComponent = lazy(() => import("./anywidget-component"));

export const AnyWidgetPlugin = createPlugin<ModelIdRef>("sp-anywidget")
  .withData(
    z.object({
      jsUrl: z.string(),
      jsHash: z.string(),
      modelId: z.string().transform((v) => v as WidgetModelId),
    }),
  )
  .withFunctions({})
  .renderer((props) => <LazyAnyWidgetComponent {...props} />);

export {
  useAnyWidgetModule,
  useMountCss,
  visibleForTesting,
} from "./anywidget-component";
