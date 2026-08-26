import { z } from "zod";

const scalarSchema = z.union([
  z.string(),
  z.number().finite(),
  z.boolean(),
  z.null(),
]);

const settingsSchema = z
  .object({
    unitOfTime: z
      .enum(["days", "weeks", "months", "quarters", "years"])
      .optional(),
    completed: z.boolean().optional(),
  })
  .strict();

const operatorSchema = z.enum([
  "equals",
  "isNull",
  "notNull",
  "inBetween",
  "inThePast",
  "inTheCurrent",
  "inPeriodToDate",
]);

const fieldTargetSchema = z
  .object({
    fieldId: z.string().min(1),
    tableName: z.string().min(1),
    isSqlColumn: z.boolean().optional(),
  })
  .strict();

const dashboardFilterRuleSchema = z
  .object({
    id: z.string().min(1),
    operator: operatorSchema,
    values: z.array(scalarSchema).optional(),
    target: fieldTargetSchema,
    tileTargets: z
      .record(z.string(), z.union([fieldTargetSchema, z.literal(false)]))
      .optional(),
    label: z.string().optional(),
    singleValue: z.boolean().optional(),
    required: z.boolean().optional(),
    disabled: z.boolean().optional(),
    settings: settingsSchema.optional(),
  })
  .strict();

const filterRuleSchema = z
  .object({
    id: z.string().min(1),
    operator: operatorSchema,
    values: z.array(scalarSchema).optional(),
    target: z.object({ fieldId: z.string().min(1) }).strict(),
    settings: settingsSchema.optional(),
  })
  .strict();

type FilterGroupInput =
  | {
      id: string;
      and: Array<FilterGroupInput | z.infer<typeof filterRuleSchema>>;
    }
  | {
      id: string;
      or: Array<FilterGroupInput | z.infer<typeof filterRuleSchema>>;
    };

const filterGroupSchema: z.ZodType<FilterGroupInput> = z.lazy(() =>
  z.union([
    z
      .object({
        id: z.string().min(1),
        and: z.array(z.union([filterGroupSchema, filterRuleSchema])),
      })
      .strict(),
    z
      .object({
        id: z.string().min(1),
        or: z.array(z.union([filterGroupSchema, filterRuleSchema])),
      })
      .strict(),
  ]),
);

const sortSchema = z
  .object({
    fieldId: z.string().min(1),
    descending: z.boolean(),
    nullsFirst: z.boolean().optional(),
  })
  .strict();

const semanticQuerySchema = z
  .object({
    kind: z.literal("semantic"),
    exploreName: z.string().min(1),
    dimensions: z.array(z.string().min(1)),
    metrics: z.array(z.string().min(1)).min(1),
    filters: z
      .object({
        dimensions: filterGroupSchema.optional(),
        metrics: filterGroupSchema.optional(),
      })
      .strict(),
    sorts: z.array(sortSchema),
    limit: z.number().int().min(1).max(10_000),
    timezone: z.string().min(1).optional(),
    pivotDimensions: z.array(z.string().min(1)).max(1).optional(),
    projectId: z.string().min(1),
    commitSha: z.string().min(7),
  })
  .strict();

const logicalTypeSchema = z.enum([
  "string",
  "number",
  "boolean",
  "date",
  "timestamp",
]);
const currencyFormatSchema = z.custom<`currency:${string}`>(
  (value) => typeof value === "string" && /^currency:[A-Z]{3}$/.test(value),
  "Expected currency: followed by a three-letter ISO code",
);
const bindingSchema = z
  .object({
    dashboardFieldId: z.string().min(1),
    outputColumn: z.string().min(1),
    logicalType: logicalTypeSchema,
  })
  .strict();

const sqlQuerySchema = z
  .object({
    kind: z.literal("sql"),
    connectionName: z.string().min(1),
    sqlTemplate: z.string().min(1),
    parameterDefinitions: z.array(
      z
        .object({
          name: z.string().min(1),
          logicalType: logicalTypeSchema,
          nullable: z.boolean(),
        })
        .strict(),
    ),
    outputBindings: z.array(bindingSchema),
    limit: z.number().int().min(1).max(10_000),
  })
  .strict();

const visualizationSchema = z.discriminatedUnion("type", [
  z
    .object({
      type: z.literal("big_number"),
      config: z
        .object({
          field: z.string().min(1),
          format: z
            .union([
              z.enum(["integer", "decimal", "compact", "percentage"]),
              currencyFormatSchema,
            ])
            .optional(),
        })
        .strict(),
    })
    .strict(),
  z
    .object({
      type: z.literal("table"),
      config: z
        .object({
          columns: z.array(z.string().min(1)).min(1),
          groups: z.array(z.string().min(1)).optional(),
        })
        .strict(),
    })
    .strict(),
  z
    .object({
      type: z.literal("cartesian"),
      config: z
        .object({
          seriesType: z.enum(["bar", "line", "area"]),
          layout: z
            .object({
              xField: z.string().min(1),
              yField: z.array(z.string().min(1)).min(1),
              stack: z.boolean().optional(),
            })
            .strict(),
        })
        .strict(),
    })
    .strict(),
]);

const chartSchema = z
  .object({
    id: z.string().min(1),
    title: z.string().min(1),
    question: z.string().min(1).max(120).optional(),
    description: z.string().optional(),
    query: z.discriminatedUnion("kind", [semanticQuerySchema, sqlQuerySchema]),
    visualization: visualizationSchema,
    signalPilot: z
      .object({
        crossFilter: z.boolean(),
        drillDimensions: z.array(z.string().min(1)).optional(),
        tableGroups: z.array(z.string().min(1)).optional(),
        customFilterBindings: z.array(bindingSchema).optional(),
        provenanceRef: z.string().min(1),
      })
      .strict(),
  })
  .strict();

const tileSchema = z
  .object({
    uuid: z.string().min(1),
    tileSlug: z.string().min(1),
    type: z.literal("saved_chart"),
    x: z.number().int().min(0).max(35),
    y: z.number().int().min(0),
    h: z.number().int().min(1),
    w: z.number().int().min(1).max(36),
    properties: z
      .object({
        title: z.string().optional(),
        hideTitle: z.boolean().optional(),
        chartName: z.string().nullable().optional(),
        chartSlug: z.string().min(1),
      })
      .strict(),
    chartId: z.string().min(1),
  })
  .strict();

export const dashboardDefinitionSchema = z
  .object({
    schemaVersion: z.literal(1),
    name: z.string().min(1),
    description: z.string().optional(),
    filters: z
      .object({
        dimensions: z.array(dashboardFilterRuleSchema),
        metrics: z.array(dashboardFilterRuleSchema),
      })
      .strict(),
    tiles: z.array(tileSchema).min(1),
    charts: z.array(chartSchema).min(1),
    signalPilot: z
      .object({
        dashboardId: z.string().min(1),
        projectId: z.string().min(1),
        connectionName: z.string().min(1),
        commitSha: z.string().min(7),
        semanticFingerprint: z.string().min(1),
        forkedFromVersionId: z.string().min(1).optional(),
        evalBindings: z
          .array(
            z
              .object({ chartId: z.string().min(1), evalId: z.string().min(1) })
              .strict(),
          )
          .optional(),
        timezone: z.string().min(1),
      })
      .strict(),
  })
  .strict()
  .superRefine((definition, context) => {
    const chartIds = new Set<string>();
    const tileIds = new Set<string>();
    const chartById = new Map(
      definition.charts.map((chart) => [chart.id, chart]),
    );
    for (const chart of definition.charts) {
      if (chartIds.has(chart.id))
        context.addIssue({
          code: "custom",
          path: ["charts"],
          message: `Duplicate chart id '${chart.id}'`,
        });
      chartIds.add(chart.id);
      const outputs = new Set(
        chart.query.kind === "semantic"
          ? [...chart.query.dimensions, ...chart.query.metrics]
          : chart.query.outputBindings.map((item) => item.outputColumn),
      );
      const encoded =
        chart.visualization.type === "big_number"
          ? [chart.visualization.config.field]
          : chart.visualization.type === "table"
            ? chart.visualization.config.columns
            : [
                chart.visualization.config.layout.xField,
                ...chart.visualization.config.layout.yField,
              ];
      for (const field of encoded) {
        if (!outputs.has(field))
          context.addIssue({
            code: "custom",
            path: ["charts", chart.id, "visualization"],
            message: `Encoding references unknown query field '${field}'`,
          });
      }
    }
    for (const tile of definition.tiles) {
      if (tileIds.has(tile.uuid))
        context.addIssue({
          code: "custom",
          path: ["tiles"],
          message: `Duplicate tile id '${tile.uuid}'`,
        });
      tileIds.add(tile.uuid);
      if (!chartById.has(tile.chartId))
        context.addIssue({
          code: "custom",
          path: ["tiles", tile.uuid, "chartId"],
          message: `Tile references unknown chart '${tile.chartId}'`,
        });
      if (tile.x + tile.w > 36)
        context.addIssue({
          code: "custom",
          path: ["tiles", tile.uuid],
          message: "Tile exceeds the 36-column grid",
        });
    }
  });
