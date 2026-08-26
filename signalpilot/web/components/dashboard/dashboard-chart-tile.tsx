"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { CircleX, RotateCw } from "lucide-react";
import {
  Button as AriaButton,
  Dialog as AriaDialog,
  DialogTrigger as AriaDialogTrigger,
  Popover as AriaPopover,
} from "react-aria-components";

import { DashboardRenderer } from "~/components/dashboard/dashboard-renderer";
import { DashboardLoadingState } from "~/components/dashboard/dashboard-loading-state";
import { DashboardConfidenceFlag } from "~/components/dashboard/dashboard-confidence-flag";
import type {
  ChartDefinition,
  DashboardFailure,
  DashboardQueryResult,
} from "~/lib/dashboard/contracts";
import {
  fieldLabel,
  formatDashboardCell,
  formatDashboardTimestamp,
} from "~/lib/dashboard/semantic-formatter";

import styles from "./dashboard-runtime.module.css";

function ResultDialog({
  chart,
  result,
  onClose,
}: {
  chart: ChartDefinition;
  result: DashboardQueryResult;
  onClose: () => void;
}) {
  const closeButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    closeButton.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return createPortal(
    <div
      className={styles.dataDialog}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
      role="dialog"
      aria-modal="true"
      aria-labelledby={`data-dialog-${chart.id}`}
    >
      <section className={styles.dataDialogPanel}>
        <header className={styles.dataDialogHeader}>
          <div>
            <span>Exact aggregated result</span>
            <h3 id={`data-dialog-${chart.id}`}>{chart.title}</h3>
            <p>
              {result.rows.length.toLocaleString(result.locale)} visible rows
            </p>
          </div>
          <button ref={closeButton} type="button" onClick={onClose}>
            Close
          </button>
        </header>
        <div
          className={styles.dataTableViewport}
          tabIndex={0}
          aria-label={`${chart.title} result table`}
        >
          <table>
            <thead>
              <tr>
                {result.columns.map((column) => (
                  <th key={column.name} scope="col">
                    {column.label ?? fieldLabel(column.name)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {result.rows.map((row, index) => (
                <tr key={index}>
                  {result.columns.map((column) => (
                    <td key={column.name}>
                      {formatDashboardCell(row[column.name], column, result)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>,
    document.body,
  );
}

export function DashboardChartTile({
  chart,
  result,
  failure,
  loading,
  onRetry,
  unaffectedFilters = 0,
  onMarkSelect,
  selectionLabel,
  onFilter,
  canFilter,
  onDrill,
  canDrill,
  drillBreadcrumb = [],
  onDrillTo,
  onExpandRow,
  onAnalyze,
  onDetails,
}: {
  chart: ChartDefinition;
  result?: DashboardQueryResult;
  failure?: DashboardFailure;
  loading?: boolean;
  onRetry?: () => void;
  unaffectedFilters?: number;
  onMarkSelect?: (mark: Record<string, unknown>) => void;
  selectionLabel?: string;
  onFilter?: () => void;
  canFilter?: boolean;
  onDrill?: () => void;
  canDrill?: boolean;
  drillBreadcrumb?: Array<{ label: string; value: string }>;
  onDrillTo?: (depth: number) => void;
  onExpandRow?: (row: Record<string, unknown>) => Promise<DashboardQueryResult>;
  onAnalyze?: () => void;
  onDetails?: () => void;
}) {
  const [showData, setShowData] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [questionOpen, setQuestionOpen] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);
  const menuPanel = useRef<HTMLDivElement>(null);
  const questionButton = useRef<HTMLButtonElement>(null);
  const isKpi = chart.visualization.type === "big_number";
  const question =
    chart.question ??
    (isKpi ? `What is our ${chart.title.toLowerCase()}?` : chart.title);
  const tileFailure =
    failure?.scope === "chart" || !result ? failure : undefined;
  useEffect(() => {
    if (!menuOpen) return;
    const dismissFromOutside = (event: MouseEvent) => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (
        menuButton.current?.contains(target) ||
        menuPanel.current?.contains(target)
      )
        return;
      setMenuOpen(false);
    };
    const dismissFromEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      setMenuOpen(false);
      window.setTimeout(() => menuButton.current?.focus(), 50);
    };
    document.addEventListener("mousedown", dismissFromOutside, true);
    document.addEventListener("keydown", dismissFromEscape);
    return () => {
      document.removeEventListener("mousedown", dismissFromOutside, true);
      document.removeEventListener("keydown", dismissFromEscape);
    };
  }, [menuOpen]);
  return (
    <section
      className={`${styles.tile} ${isKpi ? styles.kpiTile : styles.chartTile}`}
      aria-busy={loading}
    >
      <header className={styles.tileHeader}>
        <div className={styles.questionWrap}>
          {chart.description ? (
            <>
              <h2>
                <button
                  ref={questionButton}
                  type="button"
                  className={styles.questionTrigger}
                  aria-label={`About ${question}`}
                  aria-describedby={`question-description-${chart.id}`}
                  onMouseEnter={() => setQuestionOpen(true)}
                  onMouseLeave={() => setQuestionOpen(false)}
                  onFocus={() => setQuestionOpen(true)}
                  onBlur={() => setQuestionOpen(false)}
                >
                  {question}
                </button>
              </h2>
              <AriaPopover
                className={styles.questionTooltip}
                placement="bottom start"
                triggerRef={questionButton}
                isOpen={questionOpen}
                onOpenChange={setQuestionOpen}
                isNonModal
              >
                <div id={`question-description-${chart.id}`} role="tooltip">
                  {chart.description}
                </div>
              </AriaPopover>
            </>
          ) : (
            <h2>{question}</h2>
          )}
        </div>
        <DashboardConfidenceFlag chart={chart} />
        <AriaDialogTrigger
          isOpen={menuOpen}
          onOpenChange={setMenuOpen}
        >
          <AriaButton
            ref={menuButton}
            className={styles.tileMenuButton}
            aria-label={`More actions for ${chart.title}`}
          >
            •••
          </AriaButton>
          <AriaPopover
            ref={menuPanel}
            className={styles.tileMenuPanel}
            placement="bottom end"
            offset={7}
          >
            <AriaDialog
              className={styles.tileMenuDialog}
              aria-label={`Actions for ${chart.title}`}
            >
              {result ? (
                <div className={styles.tileMenuMeta}>
                  <span>
                    {result.completeness === "complete"
                      ? "Complete result"
                      : "Result may be incomplete"}
                  </span>
                  <span>
                    Updated{" "}
                    {formatDashboardTimestamp(result.freshnessAt, result)}
                  </span>
                  {result.cacheState === "stale_refreshing" ? (
                    <span>Updating cached result</span>
                  ) : result.cacheState === "cached_source_unavailable" ? (
                    <span>Showing cached data</span>
                  ) : null}
                  {unaffectedFilters ? (
                    <span>
                      {unaffectedFilters} unmapped filter
                      {unaffectedFilters === 1 ? "" : "s"}
                    </span>
                  ) : null}
                </div>
              ) : null}
              <button
                type="button"
                disabled={!result}
                onClick={() => {
                  setMenuOpen(false);
                  setShowData(true);
                }}
              >
                View data
              </button>
              {onAnalyze ? (
                <button
                  type="button"
                  disabled={!result}
                  onClick={() => {
                    setMenuOpen(false);
                    onAnalyze();
                  }}
                >
                  Analyze this change
                </button>
              ) : null}
              {onDetails ? (
                <button
                  type="button"
                  onClick={() => {
                    setMenuOpen(false);
                    onDetails();
                  }}
                >
                  Details
                </button>
              ) : null}
            </AriaDialog>
          </AriaPopover>
        </AriaDialogTrigger>
      </header>
      {drillBreadcrumb.length ? (
        <nav
          className={styles.drillBreadcrumb}
          aria-label={`${chart.title} drill path`}
        >
          <button type="button" onClick={() => onDrillTo?.(0)}>
            All
          </button>
          {drillBreadcrumb.map((step, index) => (
            <span key={`${step.label}-${index}`}>
              <span aria-hidden="true">/</span>
              <button type="button" onClick={() => onDrillTo?.(index + 1)}>
                {step.label}: {step.value}
              </button>
            </span>
          ))}
        </nav>
      ) : null}
      <div
        className={`${styles.visual} ${tileFailure && !result ? styles.visualBroken : ""}`}
      >
        {tileFailure ? (
          <div className={styles.chartBrokenState} role="status">
            <span className={styles.chartBrokenIcon} aria-hidden="true">
              <CircleX size={21} strokeWidth={1.8} />
            </span>
            <strong>Unable to display this chart</strong>
            <p>{tileFailure.message}</p>
            {!result ? (
              <span className={styles.failureAttemptedAt}>
                Last checked {new Date(tileFailure.occurredAt).toLocaleString()}
                .
              </span>
            ) : null}
            {!result && tileFailure.retryable && onRetry ? (
              <button type="button" onClick={onRetry} disabled={loading}>
                <RotateCw size={13} aria-hidden="true" />
                Retry
              </button>
            ) : null}
          </div>
        ) : null}
        {loading && !result ? (
          <DashboardLoadingState label="Loading governed data" hideLabel />
        ) : null}
        {!loading && !tileFailure && result?.rows.length === 0 ? (
          <div className={styles.state}>
            No data matches this dashboard state.
          </div>
        ) : null}
        {result?.rows.length ? (
          <DashboardRenderer
            chart={chart}
            result={result}
            onMarkClick={
              onMarkSelect ? (mark) => onMarkSelect(mark) : undefined
            }
            onExpandRow={onExpandRow}
          />
        ) : null}
      </div>
      {selectionLabel ? (
        <div
          className={styles.selectionActions}
          role="group"
          aria-label={`Actions for ${selectionLabel}`}
        >
          <span>Selected: {selectionLabel}</span>
          {onFilter ? (
            <button type="button" disabled={!canFilter} onClick={onFilter}>
              Filter dashboard
            </button>
          ) : null}
          {onDrill ? (
            <button type="button" disabled={!canDrill} onClick={onDrill}>
              Drill into value
            </button>
          ) : null}
        </div>
      ) : null}
      {showData && result ? (
        <ResultDialog
          chart={chart}
          result={result}
          onClose={() => setShowData(false)}
        />
      ) : null}
    </section>
  );
}
