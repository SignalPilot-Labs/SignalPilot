/* oxlint-disable typescript/no-explicit-any */

import { tableFromIPC } from "@uwdata/flechette";
import { batch } from "@/utils/batch-requests";
import { createLoader, type Loader } from "./vega-loader";

export function createBatchedLoader(): Loader {
  const loader = withArrowSupport(createLoader());
  const toKey = (request: unknown) => JSON.stringify(request);
  return {
    load: batch(loader.load.bind(loader) as any, toKey),
    sanitize: batch(loader.sanitize.bind(loader) as any, toKey),
    http: batch(loader.http.bind(loader) as any, toKey),
    file: batch(loader.file.bind(loader), toKey),
  };
}

/**
 * Arrow IPC embedded as a data: URL ("ARROW1" magic, base64 "QVJST1cx").
 * Headless/agent runs embed the dataframe directly because there is no
 * kernel to serve virtual files; fetching it as TEXT (vega's default)
 * mangles the binary, so it must go through the arrayBuffer path.
 */
const ARROW_DATA_URL = /^data:[^,]*;base64,QVJST1cx/;

export function isArrowUri(uri: string): boolean {
  return uri.endsWith(".arrow") || ARROW_DATA_URL.test(uri);
}

export function withArrowSupport(loader: Loader): Loader {
  return {
    ...loader,
    async load(uri: string, options?: unknown) {
      if (isArrowUri(uri)) {
        const arrow = await batchedArrowLoader(uri);
        return tableFromIPC(arrow, {
          // useProxy=true makes aggregations like year(data) fail
          useProxy: false,
        }).toArray();
      }
      return loader.load(uri, options);
    },
  };
}

/**
 * Batch requests to the same URL returning the same promise for all calls with the same key.
 */
export const batchedArrowLoader = batch(
  (url: string) => fetch(url).then((r) => r.arrayBuffer()),
  (url: string) => url,
);
