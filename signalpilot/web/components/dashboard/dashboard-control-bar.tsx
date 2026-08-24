"use client";

import { Funnel } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { request } from "~/lib/api";
import type {
  DashboardDefinition,
  DashboardFilterRule,
  DashboardRuntimeFilter,
} from "~/lib/dashboard/contracts";

import styles from "./dashboard-runtime.module.css";

type Props = {
  dashboardId: string;
  versionId: string;
  definition: DashboardDefinition;
  filters: DashboardRuntimeFilter[];
  onChange: (filters: DashboardRuntimeFilter[]) => void;
  onReset: () => void;
};

const isDateRule = (rule: DashboardFilterRule) =>
  Boolean(rule.settings?.unitOfTime) ||
  /date|time|day|month|year|at$/i.test(rule.target.fieldId);

function dateInTimezone(timezone: string, dayOffset: number): string {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const value = Object.fromEntries(
    parts.map((part) => [part.type, part.value]),
  );
  return new Date(
    Date.UTC(
      Number(value.year),
      Number(value.month) - 1,
      Number(value.day) + dayOffset,
    ),
  )
    .toISOString()
    .slice(0, 10);
}

function DateControl({
  rule,
  active,
  timezone,
  onChange,
}: {
  rule: DashboardFilterRule;
  active?: DashboardRuntimeFilter;
  timezone: string;
  onChange: (next?: DashboardRuntimeFilter) => void;
}) {
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const preset =
    active?.operator === "inThePast"
      ? `last-${active.values?.[0] ?? 7}`
      : active?.operator === "inTheCurrent"
        ? "today"
        : active?.operator === "inPeriodToDate"
          ? `${active.settings?.unitOfTime ?? "months"}-to-date`
          : active?.operator === "inBetween"
            ? "absolute"
            : "all";
  const applyPreset = (value: string) => {
    if (value === "all") return onChange();
    if (value === "today") {
      return onChange({
        id: rule.id,
        operator: "inTheCurrent",
        values: [],
        settings: { unitOfTime: "days" },
      });
    }
    if (value === "yesterday") {
      return onChange({
        id: rule.id,
        operator: "inBetween",
        values: [dateInTimezone(timezone, -1), dateInTimezone(timezone, 0)],
      });
    }
    if (value.endsWith("-to-date")) {
      return onChange({
        id: rule.id,
        operator: "inPeriodToDate",
        values: [],
        settings: {
          unitOfTime: value.replace("-to-date", "") as
            | "months"
            | "quarters"
            | "years",
        },
      });
    }
    if (value.startsWith("last-")) {
      return onChange({
        id: rule.id,
        operator: "inThePast",
        values: [Number(value.slice(5))],
        settings: { unitOfTime: "days" },
      });
    }
  };
  return (
    <div className={styles.control}>
      <label htmlFor={`filter-${rule.id}`}>
        {rule.label ?? rule.target.fieldId}
      </label>
      <select
        id={`filter-${rule.id}`}
        value={preset}
        onChange={(event) => applyPreset(event.target.value)}
      >
        <option value="all">All dates</option>
        <option value="today">Today</option>
        <option value="yesterday">Yesterday</option>
        <option value="last-7">Last 7 days</option>
        <option value="last-30">Last 30 days</option>
        <option value="last-90">Last 90 days</option>
        <option value="months-to-date">Month to date</option>
        <option value="quarters-to-date">Quarter to date</option>
        <option value="years-to-date">Year to date</option>
        <option value="absolute">Absolute range</option>
      </select>
      {preset === "absolute" ? (
        <span className={styles.absoluteRange}>
          <input
            aria-label={`${rule.label ?? rule.id} start`}
            type="date"
            value={start}
            onChange={(event) => setStart(event.target.value)}
          />
          <input
            aria-label={`${rule.label ?? rule.id} end`}
            type="date"
            value={end}
            onChange={(event) => {
              setEnd(event.target.value);
              if (start && event.target.value) {
                const exclusiveEnd = new Date(
                  `${event.target.value}T00:00:00Z`,
                );
                exclusiveEnd.setUTCDate(exclusiveEnd.getUTCDate() + 1);
                onChange({
                  id: rule.id,
                  operator: "inBetween",
                  values: [start, exclusiveEnd.toISOString().slice(0, 10)],
                });
              }
            }}
          />
        </span>
      ) : null}
    </div>
  );
}

function DimensionControl({
  dashboardId,
  versionId,
  rule,
  active,
  onChange,
}: {
  dashboardId: string;
  versionId: string;
  rule: DashboardFilterRule;
  active?: DashboardRuntimeFilter;
  onChange: (next?: DashboardRuntimeFilter) => void;
}) {
  const [values, setValues] = useState<Array<string | number | boolean | null>>(
    [],
  );
  useEffect(() => {
    const controller = new AbortController();
    request<{ values: Array<string | number | boolean | null> }>(
      `/api/dashboards/${dashboardId}/filters/${encodeURIComponent(rule.id)}/values`,
      {
        method: "POST",
        body: JSON.stringify({ version_id: versionId, limit: 100 }),
        signal: controller.signal,
      },
    )
      .then((response) => setValues(response.values))
      .catch(() => undefined);
    return () => controller.abort();
  }, [dashboardId, rule.id, versionId]);
  const selected = active?.values?.[0];
  const selectValue =
    active?.operator === "isNull"
      ? "__is_null__"
      : active?.operator === "notNull"
        ? "__not_null__"
        : selected === undefined
          ? ""
          : String(selected);
  return (
    <div className={styles.control}>
      <label htmlFor={`filter-${rule.id}`}>
        {rule.label ?? rule.target.fieldId}
      </label>
      <select
        id={`filter-${rule.id}`}
        value={selectValue}
        onChange={(event) => {
          const next = event.target.value;
          if (!next) return onChange();
          if (next === "__is_null__")
            return onChange({ id: rule.id, operator: "isNull" });
          if (next === "__not_null__")
            return onChange({ id: rule.id, operator: "notNull" });
          const original = values.find((value) => String(value) === next);
          onChange({ id: rule.id, operator: "equals", values: [original] });
        }}
      >
        <option value="">is any value</option>
        {values.map((value) => (
          <option key={String(value)} value={String(value)}>
            {String(value)}
          </option>
        ))}
        <option value="__is_null__">is null</option>
        <option value="__not_null__">is not null</option>
      </select>
    </div>
  );
}

export function DashboardControlBar(props: Props) {
  const activeById = useMemo(
    () => new Map(props.filters.map((filter) => [filter.id, filter])),
    [props.filters],
  );
  if (props.definition.filters.dimensions.length === 0) return null;
  return (
    <section className={styles.controlBar} aria-label="Dashboard filters">
      <Funnel className={styles.filterIcon} size={17} aria-hidden="true" />
      <div className={styles.controls}>
        {props.definition.filters.dimensions.map((rule) => {
          const update = (next?: DashboardRuntimeFilter) =>
            props.onChange([
              ...props.filters.filter((filter) => filter.id !== rule.id),
              ...(next ? [next] : []),
            ]);
          return isDateRule(rule) ? (
            <DateControl
              key={rule.id}
              rule={rule}
              active={activeById.get(rule.id)}
              timezone={props.definition.signalPilot.timezone}
              onChange={update}
            />
          ) : (
            <DimensionControl
              key={rule.id}
              dashboardId={props.dashboardId}
              versionId={props.versionId}
              rule={rule}
              active={activeById.get(rule.id)}
              onChange={update}
            />
          );
        })}
      </div>
      <div className={styles.filterChips}>
        {props.filters.length ? (
          <button type="button" onClick={props.onReset}>
            Reset filters
          </button>
        ) : null}
      </div>
    </section>
  );
}
