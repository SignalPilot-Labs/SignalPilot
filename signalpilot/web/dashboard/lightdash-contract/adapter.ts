import { UnsupportedDashboardFeatureError } from "./errors";
import { dashboardDefinitionSchema } from "./schema";
import type {
  DashboardDefinition,
  LightdashCompatibilityFixture,
} from "./types";

const supportedVisualizationTypes = new Set(["big_number", "table", "cartesian"]);

export function fromLightdashFixture(input: unknown): DashboardDefinition {
  if (!input || typeof input !== "object") {
    throw new UnsupportedDashboardFeatureError("fixture", "non-object fixture");
  }
  const fixture = input as LightdashCompatibilityFixture;
  for (const [index, tile] of (fixture.dashboard?.tiles ?? []).entries()) {
    if (tile.type !== "saved_chart") {
      throw new UnsupportedDashboardFeatureError(
        `dashboard.tiles[${index}].type`,
        String(tile.type),
      );
    }
  }
  for (const [index, chart] of (fixture.charts ?? []).entries()) {
    const type = (chart.visualization as { type?: string })?.type;
    if (!type || !supportedVisualizationTypes.has(type)) {
      throw new UnsupportedDashboardFeatureError(
        `charts[${index}].visualization.type`,
        type ?? "missing",
      );
    }
    if (
      type === "cartesian" &&
      !(new Set(["bar", "line", "area"]).has(
        (chart.visualization as { config?: { seriesType?: string } }).config
          ?.seriesType ?? "",
      ))
    ) {
      throw new UnsupportedDashboardFeatureError(
        `charts[${index}].visualization.config.seriesType`,
        (chart.visualization as { config?: { seriesType?: string } }).config
          ?.seriesType ?? "missing",
      );
    }
  }

  return dashboardDefinitionSchema.parse({
    schemaVersion: 1,
    name: fixture.dashboard.name,
    description: fixture.dashboard.description,
    filters: fixture.dashboard.filters,
    tiles: fixture.dashboard.tiles,
    charts: fixture.charts,
    signalPilot: fixture.signalPilot,
  });
}

export function toLightdashFixture(
  definitionInput: unknown,
  version = 1,
): LightdashCompatibilityFixture {
  const definition = dashboardDefinitionSchema.parse(definitionInput);
  return {
    dashboard: {
      name: definition.name,
      ...(definition.description ? { description: definition.description } : {}),
      version,
      filters: definition.filters,
      tiles: definition.tiles,
    },
    charts: definition.charts,
    signalPilot: definition.signalPilot,
  };
}
