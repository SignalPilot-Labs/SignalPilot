import React, { lazy } from "react";
import { z } from "zod";
import { createPlugin } from "@/plugins/core/builder";
import type { WidgetModelId } from "@/plugins/impl/anywidget/types";

const LazyMplInteractiveComponent = lazy(
  () => import("./mpl-interactive-component"),
);

interface ModelIdRef {
  model_id: WidgetModelId;
}

export const MplInteractivePlugin = createPlugin<ModelIdRef>(
  "sp-mpl-interactive",
)
  .withData(
    z.object({
      mplJsUrl: z.string(),
      cssUrl: z.string(),
      toolbarImages: z.record(z.string(), z.string()),
      width: z.number(),
      height: z.number(),
    }),
  )
  .withFunctions({})
  .renderer((props) => <LazyMplInteractiveComponent {...props} />);

export { visibleForTesting } from "./mpl-interactive-component";
