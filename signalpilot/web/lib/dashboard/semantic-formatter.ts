import type {
  DashboardLogicalType,
  DashboardResultColumn,
  DashboardValueFormat,
} from "~/lib/dashboard/contracts";

export type DashboardFormatContext = {
  locale: string;
  timezone: string;
};

export type DashboardValueMetadata = {
  logicalType?: DashboardLogicalType;
  format?: DashboardValueFormat;
  currencyCode?: string;
};

const fallbackContext: DashboardFormatContext = {
  locale: "en-US",
  timezone: "UTC",
};

export function viewerLocale(): string {
  return typeof navigator === "undefined"
    ? fallbackContext.locale
    : navigator.language;
}

export function fieldLabel(fieldId: string): string {
  const leaf = fieldId.split(".").at(-1) ?? fieldId;
  return leaf
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function formatDashboardValue(
  value: unknown,
  metadata: DashboardValueMetadata = {},
  context: DashboardFormatContext = fallbackContext,
): string {
  if (value === null || value === undefined) return "—";
  const { format, logicalType } = metadata;
  const numericValue =
    typeof value === "number"
      ? value
      : logicalType === "number" &&
          typeof value === "string" &&
          /^-?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?$/i.test(value.trim())
        ? Number(value)
        : undefined;
  if (numericValue !== undefined && Number.isFinite(numericValue)) {
    if (format === "integer") {
      return new Intl.NumberFormat(context.locale, {
        maximumFractionDigits: 0,
      }).format(numericValue);
    }
    if (format === "compact") {
      return new Intl.NumberFormat(context.locale, {
        notation: "compact",
        maximumFractionDigits: 1,
      }).format(numericValue);
    }
    if (format === "percentage") {
      return new Intl.NumberFormat(context.locale, {
        style: "percent",
        maximumFractionDigits: 1,
      }).format(numericValue);
    }
    const currencyCode =
      metadata.currencyCode ??
      (format?.startsWith("currency:")
        ? format.slice("currency:".length)
        : undefined);
    if (currencyCode) {
      return new Intl.NumberFormat(context.locale, {
        style: "currency",
        currency: currencyCode,
        currencyDisplay: "narrowSymbol",
      }).format(numericValue);
    }
    return new Intl.NumberFormat(context.locale, {
      maximumFractionDigits: format === "decimal" ? 2 : 2,
    }).format(numericValue);
  }
  if (logicalType === "boolean" && typeof value === "boolean") {
    return value ? "Yes" : "No";
  }
  if (
    (logicalType === "date" || logicalType === "timestamp") &&
    (typeof value === "string" || value instanceof Date)
  ) {
    const date = value instanceof Date ? value : new Date(value);
    if (!Number.isNaN(date.valueOf())) {
      return new Intl.DateTimeFormat(
        context.locale,
        logicalType === "date"
          ? { dateStyle: "medium", timeZone: context.timezone }
          : {
              dateStyle: "medium",
              timeStyle: "short",
              timeZone: context.timezone,
            },
      ).format(date);
    }
  }
  return String(value);
}

export function formatDashboardCell(
  value: unknown,
  column: DashboardResultColumn,
  context: DashboardFormatContext,
): string {
  return formatDashboardValue(value, column, context);
}

export function formatDashboardTimestamp(
  value: string,
  context: DashboardFormatContext,
): string {
  return formatDashboardValue(value, { logicalType: "timestamp" }, context);
}
