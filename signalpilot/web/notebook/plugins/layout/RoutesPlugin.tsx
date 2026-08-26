import { type JSX, lazy } from "react";
import { z } from "zod";
import type {
  IStatelessPlugin,
  IStatelessPluginProps,
} from "../stateless-plugin";

interface Data {
  /**
   * Route paths to render.
   */
  routes: string[];
}

const LazyRoutes = lazy(() => import("./routes/routes-component"));

export class RoutesPlugin implements IStatelessPlugin<Data> {
  tagName = "sp-routes";

  validator = z.object({
    routes: z.array(z.string()),
  });

  render(props: IStatelessPluginProps<Data>): JSX.Element {
    return (
      <LazyRoutes routes={props.data.routes}>{props.children}</LazyRoutes>
    );
  }
}
