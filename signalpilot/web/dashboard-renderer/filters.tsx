"use client";

import { useMemo } from "react";

import type { DatasetRows } from "./datasets";
import { filterBindsTo, type FilterState } from "./prepare";
import type { DashboardFilter, DashboardSpec } from "./schema";

const INPUT_CLASS =
  "h-7 rounded border border-[var(--sp-dash-border)] bg-[var(--sp-dash-surface)] px-2 text-[12px] text-[var(--sp-dash-text)] outline-none focus:border-[var(--sp-dash-accent)]";

function asRecord(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function distinctValues(rows: DatasetRows | undefined, column: string): string[] {
  const seen = new Set<string>();
  for (const row of rows ?? []) {
    const value = row[column];
    if (value === null || value === undefined) continue;
    seen.add(String(value));
    if (seen.size >= 200) break;
  }
  return [...seen];
}

function FilterControl({
  filter,
  value,
  rows,
  onChange,
}: {
  filter: DashboardFilter;
  value: unknown;
  rows: DatasetRows | undefined;
  onChange: (next: unknown) => void;
}) {
  const options = useMemo(
    () => (filter.type === "equals" || filter.type === "in" ? distinctValues(rows, filter.column) : []),
    [filter.type, filter.column, rows],
  );
  if (filter.type === "equals") {
    const current = value === null || value === undefined ? "" : String(value);
    return (
      <select
        className={INPUT_CLASS}
        value={current}
        onChange={(event) => onChange(event.target.value === "" ? null : event.target.value)}
        aria-label={filter.label}
      >
        <option value="">All</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    );
  }
  if (filter.type === "in") {
    const selected = new Set(Array.isArray(value) ? value.map(String) : []);
    return (
      <div className="flex flex-wrap gap-1" role="group" aria-label={filter.label}>
        {options.map((option) => {
          const active = selected.has(option);
          return (
            <button
              key={option}
              type="button"
              aria-pressed={active}
              onClick={() => {
                const next = new Set(selected);
                if (active) next.delete(option);
                else next.add(option);
                onChange([...next]);
              }}
              className={`h-6 rounded-full border px-2 text-[11px] ${
                active
                  ? "border-[var(--sp-dash-accent)] bg-[var(--sp-dash-accent)] text-white"
                  : "border-[var(--sp-dash-border)] bg-[var(--sp-dash-surface)] text-[var(--sp-dash-text-secondary)]"
              }`}
            >
              {option}
            </button>
          );
        })}
      </div>
    );
  }
  const range = asRecord(value);
  const isDate = filter.type === "date_range";
  const lowKey = isDate ? "from" : "min";
  const highKey = isDate ? "to" : "max";
  const update = (key: string, raw: string) => {
    const next = { ...range };
    if (raw === "") delete next[key];
    else next[key] = isDate ? raw : Number(raw);
    onChange(next);
  };
  const text = (key: string) => {
    const current = range[key];
    return current === null || current === undefined ? "" : String(current);
  };
  return (
    <div className="flex items-center gap-1" role="group" aria-label={filter.label}>
      <input
        type={isDate ? "date" : "number"}
        className={INPUT_CLASS}
        value={text(lowKey)}
        onChange={(event) => update(lowKey, event.target.value)}
        aria-label={`${filter.label} ${lowKey}`}
      />
      <span className="text-[11px] text-[var(--sp-dash-text-muted)]">to</span>
      <input
        type={isDate ? "date" : "number"}
        className={INPUT_CLASS}
        value={text(highKey)}
        onChange={(event) => update(highKey, event.target.value)}
        aria-label={`${filter.label} ${highKey}`}
      />
    </div>
  );
}

/** Rows the filter draws its choices from: its dataset, or every dataset with the column. */
function boundRows(filter: DashboardFilter, datasets: Record<string, DatasetRows>): DatasetRows {
  const rows: DatasetRows = [];
  for (const [name, datasetRows] of Object.entries(datasets)) {
    if (filterBindsTo(filter, name, datasetRows)) rows.push(...datasetRows);
  }
  return rows;
}

export function FilterBar({
  spec,
  datasets,
  filterState,
  onChange,
}: {
  spec: DashboardSpec;
  datasets: Record<string, DatasetRows>;
  filterState: FilterState;
  onChange: (next: FilterState) => void;
}) {
  const filters = spec.filters ?? [];
  if (filters.length === 0) return null;
  return (
    <div
      data-dashboard-filters=""
      className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-[var(--sp-dash-border)] bg-[var(--sp-dash-surface)] px-3 py-2"
    >
      {filters.map((filter) => (
        <label key={filter.id} className="flex items-center gap-2 text-[12px] text-[var(--sp-dash-text-secondary)]">
          <span className="font-medium">{filter.label}</span>
          <FilterControl
            filter={filter}
            value={Object.prototype.hasOwnProperty.call(filterState, filter.id) ? filterState[filter.id] : filter.default}
            rows={boundRows(filter, datasets)}
            onChange={(next) => onChange({ ...filterState, [filter.id]: next })}
          />
        </label>
      ))}
    </div>
  );
}
