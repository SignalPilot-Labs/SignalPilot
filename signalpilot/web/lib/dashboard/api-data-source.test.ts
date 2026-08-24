import { describe, expect, it } from "vitest";

import { semanticColumnMetadata } from "~/lib/dashboard/api-data-source";

describe("dashboard receipt semantic metadata", () => {
  it("recovers currency formatting from semantic metrics for cached results", () => {
    expect(
      semanticColumnMetadata(
        {
          semantic_definition: {
            metrics: [
              {
                field_id: "orders.net_revenue",
                label: "Net Revenue",
                format: "currency:USD",
              },
            ],
          },
        },
        "orders.net_revenue",
      ),
    ).toEqual({
      label: "Net Revenue",
      format: "currency:USD",
      currencyCode: "USD",
    });
  });
});
