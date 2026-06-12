import { dequal as isEqual } from "dequal";
import { Code2Icon, DatabaseIcon, FunctionSquareIcon } from "lucide-react";
import {
  type JSX,
  memo,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import type { DownloadAsArgs } from "@/components/data-table/schemas";
import type { FieldTypesWithExternalType } from "@/components/data-table/types";
import { ReadonlyCode } from "@/components/editor/code/readonly-python-code";
import { Spinner } from "@/components/icons/spinner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAsyncData } from "@/hooks/useAsyncData";
import { Arrays } from "@/utils/arrays";
import { Functions } from "@/utils/functions";
import { ErrorBanner } from "../common/error-banner";
import { LoadingDataTableComponent, TableProviders } from "../DataTablePlugin";
import { TransformPanel, type TransformPanelHandle } from "./panel";
import type { FilterGroupType, Transformations } from "./schema";
import type { ColumnDataTypes } from "./types";

type CsvURL = string;
type TableData<T> = T[] | CsvURL;

interface Data {
  label?: string | null;
  columns: ColumnDataTypes;
  dataframeName?: string;
  pageSize: number;
  showDownload: boolean;
  lazy: boolean;
}

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

type S = Transformations | undefined;

interface DataTableProps extends Data, PluginFunctions {
  value: S;
  setValue: (value: S) => void;
  host: HTMLElement;
  showDownload: boolean;
  download_as: DownloadAsArgs;
}

const EMPTY: Transformations = {
  transforms: [],
};

const DataFrameComponentInner = memo(
  ({
    columns,
    dataframeName: _dataframeName,
    pageSize,
    showDownload,
    lazy,
    value,
    setValue,
    get_dataframe,
    get_column_values,
    search,
    download_as,
    host,
  }: DataTableProps): JSX.Element => {
    const { data, error, isPending } = useAsyncData(
      () => get_dataframe({}),
      [value?.transforms],
    );

    const {
      url,
      total_rows,
      row_headers,
      field_types,
      column_types_per_step,
      python_code,
      sql_code,
      size_bytes,
    } = data || {};

    const totalColumns = field_types?.length;

    const [internalValue, setInternalValue] = useState<Transformations>(
      value || EMPTY,
    );

    const transformPanelRef = useRef<TransformPanelHandle>(null);

    const transformTab = "transform";

    const handleTabChange = useCallback(
      (newTab: string) => {
        if (lazy && newTab !== transformTab) {
          transformPanelRef.current?.submit();
        }
      },
      [lazy],
    );

    const prevValueRef = useRef(internalValue);

    useEffect(() => {
      prevValueRef.current = internalValue;
    });

    useEffect(() => {
      const prevValue = prevValueRef.current;
      if (value?.transforms.length !== prevValue.transforms.length) {
        setValue(prevValue);
      }
    }, [data, value?.transforms.length, prevValueRef, setValue]);

    return (
      <div>
        <Tabs defaultValue={transformTab} onValueChange={handleTabChange}>
          <div className="flex items-center gap-2">
            <TabsList className="h-8">
              <TabsTrigger value={transformTab} className="text-xs py-1">
                <FunctionSquareIcon className="w-3 h-3 mr-2" />
                Transform
              </TabsTrigger>
              {python_code && (
                <TabsTrigger value="python-code" className="text-xs py-1">
                  <Code2Icon className="w-3 h-3 mr-2" />
                  Python Code
                </TabsTrigger>
              )}
              {sql_code && (
                <TabsTrigger value="sql-code" className="text-xs py-1">
                  <DatabaseIcon className="w-3 h-3 mr-2" />
                  SQL Code
                </TabsTrigger>
              )}
              <div className="grow" />
            </TabsList>
            {isPending && <Spinner size="small" />}
          </div>
          <TabsContent
            value="transform"
            className="mt-1 border rounded-t overflow-hidden"
          >
            <TransformPanel
              ref={transformPanelRef}
              initialValue={internalValue}
              columns={columns}
              onChange={(newValue) => {
                if (isEqual(newValue, value)) {
                  return;
                }
                setValue(newValue);
                setInternalValue(newValue);
              }}
              onInvalidChange={setInternalValue}
              getColumnValues={get_column_values}
              columnTypesPerStep={column_types_per_step}
              lazy={lazy}
            />
          </TabsContent>
          {python_code && (
            <TabsContent
              value="python-code"
              className="mt-1 border rounded-t overflow-hidden"
            >
              <ReadonlyCode
                minHeight="215px"
                maxHeight="215px"
                code={python_code}
                language="python"
              />
            </TabsContent>
          )}
          {sql_code && (
            <TabsContent
              value="sql-code"
              className="mt-1 border rounded-t overflow-hidden"
            >
              <ReadonlyCode
                minHeight="215px"
                maxHeight="215px"
                code={sql_code}
                language="sql"
              />
            </TabsContent>
          )}
        </Tabs>
        {error && <ErrorBanner error={error} />}
        <LoadingDataTableComponent
          label={null}
          className="rounded-b border-x border-b"
          data={url || ""}
          hasStableRowId={false}
          totalRows={total_rows ?? 0}
          sizeBytes={size_bytes ?? null}
          totalColumns={totalColumns ?? 0}
          maxColumns="all"
          pageSize={pageSize}
          pagination={true}
          fieldTypes={field_types}
          rowHeaders={row_headers || Arrays.EMPTY}
          showDownload={showDownload}
          download_as={download_as}
          enableSearch={false}
          showFilters={false}
          search={search}
          showColumnSummaries={false}
          showDataTypes={true}
          get_column_summaries={getColumnSummaries}
          showPageSizeSelector={(total_rows && total_rows > 5) || false}
          showColumnExplorer={false}
          showRowExplorer={true}
          showChartBuilder={false}
          value={Arrays.EMPTY}
          setValue={Functions.NOOP}
          selection={null}
          lazy={false}
          host={host}
        />
      </div>
    );
  },
);
DataFrameComponentInner.displayName = "DataFrameComponent";

function getColumnSummaries() {
  return Promise.resolve({
    data: null,
    stats: {},
    bin_values: {},
    value_counts: {},
    show_charts: false,
  });
}

export default function DataFrameComponent(props: DataTableProps): JSX.Element {
  return (
    <TableProviders>
      <DataFrameComponentInner {...props} />
    </TableProviders>
  );
}
DataFrameComponent.displayName = "DataFrameComponent";
