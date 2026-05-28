import { getRuntimeManager } from "../runtime/config";
import { isStaticNotebook } from "../static/static-state";
import { createLazyRequests } from "./requests-lazy";
import { createNetworkRequests } from "./requests-network";
import { createStaticRequests } from "./requests-static";
import { createErrorToastingRequests } from "./requests-toasting";
import type { EditRequests, RunRequests } from "./types";

export function resolveRequestClient(): EditRequests & RunRequests {
  let base: EditRequests & RunRequests;
  if (isStaticNotebook()) {
    base = createStaticRequests();
  } else {
    base = createLazyRequests(createNetworkRequests(), () =>
      getRuntimeManager(),
    );
  }
  return createErrorToastingRequests(base);
}
