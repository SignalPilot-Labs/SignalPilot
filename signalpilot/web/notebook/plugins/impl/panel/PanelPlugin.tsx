import React, { lazy } from "react";
import { z } from "zod";
import { createPlugin } from "@/plugins/core/builder";
import { rpc } from "@/plugins/core/rpc";

type T = Record<string, unknown>;

// oxlint-disable-next-line typescript/consistent-type-definitions
type PluginFunctions = {
  send_to_widget: <T>(req: {
    message?: unknown;
    buffers?: unknown;
  }) => Promise<null | undefined>;
};

const LazyPanelComponent = lazy(() => import("./panel-component"));

export const PanelPlugin = createPlugin<T>("sp-panel")
  .withData(
    z.object({
      extensionUrl: z.string().nullable(),
      docs_json: z.record(z.string(), z.unknown()),
      render_json: z
        .object({
          roots: z.record(z.string(), z.string()),
        })
        .catchall(z.unknown()),
    }),
  )
  .withFunctions<PluginFunctions>({
    send_to_widget: rpc
      .input(
        z.object({
          message: z.unknown(),
          buffers: z.array(z.string()),
        }),
      )
      .output(z.null().optional()),
  })
  .renderer((props) => <LazyPanelComponent {...props} />);

export { loadPanelExtension } from "./panel-component";
