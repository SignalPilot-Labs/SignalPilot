import React, { lazy } from "react";
import { z } from "zod";
import {
  type DownloadAsArgs,
  DownloadAsSchema,
} from "@/components/data-table/schemas";
import type { FieldTypesWithExternalType } from "@/components/data-table/types";
import { createPlugin } from "@/plugins/core/builder";
import { rpc } from "@/plugins/core/rpc";
import type { DataType } from "../vega/vega-loader";
import {
  FilterGroupSchema,
  type FilterGroupType,
  columnToFieldTypesSchema,
  type Transformations,
} from "./schema";
import type { ColumnId } from "./types";

type CsvURL = string;
type TableData<T> = T[] | CsvURL;

// oxlint-disable-next-line typescript/consistent-type-definitions
type PluginFunctions = {
  get_dataframe: (req: {}) => Promise<{
    url: string;
    total_rows: number;
    row_headers: FieldTypesWithExternalType;
    field_types: FieldTypesWithExternalType | null;
    column_types_per_step: FieldTypesWithExternalType[];
    python_code?: string | null;
    sql_code?: string | null;
    size_bytes?: number | null;
  }>;
  get_column_values: (req: { column: string }) => Promise<{
    values: unknown[];
    too_many_values: boolean;
  }>;
  search: <T>(req: {
    sort?: {
      by: string;
      descending: boolean;
    }[];
    query?: string;
    filters?: FilterGroupType;
    page_number: number;
    page_size: number;
  }) => Promise<{
    data: TableData<T>;
    total_rows: number;
    size_bytes?: number | null;
  }>;
  download_as: DownloadAsArgs;
};

// Value is selection, but it is not currently exposed to the user
type S = Transformations | undefined;

const LazyDataFrameComponent = lazy(() => import("./data-frame-component"));

export const DataFramePlugin = createPlugin<S>("sp-dataframe")
  .withData(
    z.object({
      label: z.string().nullish(),
      pageSize: z.number().default(5),
      showDownload: z.boolean().default(true),
      dataframeName: z.string().optional(),
      columns: z
        .array(z.tuple([z.string().or(z.number()), z.string(), z.string()]))
        .transform((value) => {
          const map = new Map<ColumnId, string>();
          value.forEach(([key, dataType]) => {
            map.set(key as ColumnId, dataType as DataType);
          });
          return map;
        }),
      lazy: z.boolean().default(false),
    }),
  )
  .withFunctions<PluginFunctions>({
    // Get the data as a URL
    get_dataframe: rpc.input(z.object({})).output(
      z.object({
        url: z.string(),
        total_rows: z.number(),
        row_headers: columnToFieldTypesSchema,
        field_types: columnToFieldTypesSchema,
        column_types_per_step: z.array(columnToFieldTypesSchema),
        python_code: z.string().nullish(),
        sql_code: z.string().nullish(),
        size_bytes: z.number().nullish(),
      }),
    ),
    get_column_values: rpc.input(z.object({ column: z.string() })).output(
      z.object({
        values: z.array(z.any()),
        too_many_values: z.boolean(),
      }),
    ),
    search: rpc
      .input(
        z.object({
          sort: z
            .array(
              z.object({
                by: z.string(),
                descending: z.boolean(),
              }),
            )
            .optional(),
          query: z.string().optional(),
          filters: FilterGroupSchema.optional(),
          page_number: z.number(),
          page_size: z.number(),
        }),
      )
      .output(
        z.object({
          data: z.union([z.string(), z.array(z.object({}).passthrough())]),
          total_rows: z.number(),
          size_bytes: z.number().nullish(),
        }),
      ),
    download_as: DownloadAsSchema,
  })
  .renderer((props) => (
    <LazyDataFrameComponent
      {...props.data}
      {...props.functions}
      value={props.value}
      setValue={props.setValue}
      host={props.host}
    />
  ));
