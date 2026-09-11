"use client";

/**
 * Embeddable lineage view: the /lineage/<model>[/raw] visual (staged focus
 * cone, focus panel, raw tables, inspector) without the page chrome. Hosts
 * such as the chat lineage modal size it with a flex/fixed-height container.
 */

import { DbtMapPage } from "./dbt-map-page";
import type { MapStatus } from "./use-dbt-map";

export type { MapStatus };

export function LineageEmbed({
  modelName,
  projectId,
  raw = false,
  onStatusChange,
}: {
  /** Model ref from the deep link: bare name or dbt unique_id. */
  modelName: string;
  projectId: string;
  /** Start on the Raw Tables panel. */
  raw?: boolean;
  onStatusChange?: (status: MapStatus) => void;
}) {
  // No key: a new model or project flows in as props and the mounted page
  // refocuses from the cache instead of refetching the graph.
  return (
    <DbtMapPage
      route={{ ref: modelName, raw, projectId }}
      embedded
      onStatusChange={onStatusChange}
    />
  );
}
