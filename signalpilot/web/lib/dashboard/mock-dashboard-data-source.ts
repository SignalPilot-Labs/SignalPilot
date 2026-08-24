import type {
  DashboardDataSource,
  DashboardQueryResult,
} from "~/lib/dashboard/contracts";

const regions = [
  {
    region: "Northeast",
    revenue: 520_000,
    customers: [
      { customer: "Acme Waste", revenue: 230_000 },
      { customer: "Northstar Logistics", revenue: 170_000 },
      { customer: "Evergreen Services", revenue: 120_000 },
    ],
  },
  {
    region: "Southeast",
    revenue: 410_000,
    customers: [
      { customer: "Coastal Recovery", revenue: 180_000 },
      { customer: "Sunbelt Disposal", revenue: 140_000 },
      { customer: "Metro Hauling", revenue: 90_000 },
    ],
  },
  {
    region: "West",
    revenue: 375_000,
    customers: [
      { customer: "Pacific Environmental", revenue: 175_000 },
      { customer: "Golden State Waste", revenue: 125_000 },
      { customer: "Canyon Services", revenue: 75_000 },
    ],
  },
  {
    region: "Midwest",
    revenue: 290_000,
    customers: [
      { customer: "Heartland Recycling", revenue: 140_000 },
      { customer: "Lakeside Waste", revenue: 90_000 },
      { customer: "Prairie Disposal", revenue: 60_000 },
    ],
  },
];

function resultFor(
  queryRef: string,
  regionFilter: unknown,
  drilled: boolean,
): DashboardQueryResult {
  const filtered = regionFilter
    ? regions.filter(({ region }) => region === regionFilter)
    : regions;
  const multiplier = queryRef.includes("margin") ? 0.42 : 1;
  const dimension = drilled ? "customer" : "region";
  const rows = drilled
    ? filtered.flatMap(({ customers }) =>
        customers.map(({ customer, revenue }) => ({
          customer,
          revenue: Math.round(revenue * multiplier),
        })),
      )
    : filtered.map(({ region, revenue }) => ({
        region,
        revenue: Math.round(revenue * multiplier),
      }));

  return {
    resultId: "result-dashboard-prototype",
    executionId: "execution-dashboard-prototype",
    columns: [
      {
        name: dimension,
        logicalType: "string",
        nullable: false,
        label: drilled ? "Customer" : "Region",
      },
      {
        name: "revenue",
        logicalType: "number",
        nullable: false,
        label: queryRef.includes("margin") ? "Gross margin" : "Revenue",
      },
    ],
    rows,
    completeness: "complete",
    freshnessAt: "2026-08-21T12:00:00Z",
    timezone: "UTC",
    locale: "en-US",
  };
}

export const mockDashboardRegions = regions;

export const mockDashboardDataSource: DashboardDataSource = {
  async loadTile(_tile, chart, options, signal) {
    await new Promise<void>((resolve, reject) => {
      const timeout = window.setTimeout(resolve, 80);
      signal.addEventListener(
        "abort",
        () => {
          window.clearTimeout(timeout);
          reject(new DOMException("Dashboard query cancelled", "AbortError"));
        },
        { once: true },
      );
    });
    return resultFor(
      chart.id,
      options.filters.find(({ field }) => field === "region")?.value,
      options.drillPath.some(({ field }) => field === "region"),
    );
  },
};
