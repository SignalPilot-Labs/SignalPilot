import type { LinkKind } from "@/lib/dbt-links/types";

export const KIND_LABEL: Record<LinkKind, string> = {
  native_upload: "Native upload",
  github: "GitHub",
  dbt_cloud: "dbt Cloud",
};
