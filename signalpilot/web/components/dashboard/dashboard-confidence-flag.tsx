import { BadgeAlert, BadgeCheck } from "lucide-react";

import type { ChartDefinition } from "~/lib/dashboard/contracts";
import {
  chartConfidence,
  confidenceExplanation,
} from "~/lib/dashboard/confidence";

import styles from "./dashboard-runtime.module.css";

export function DashboardConfidenceFlag({ chart }: { chart: ChartDefinition }) {
  const confidence = chartConfidence(chart);
  const explanation = confidenceExplanation(chart);
  return (
    <span className={styles.confidenceWrap}>
      <span
        className={`${styles.confidenceFlag} ${confidence === "high" ? styles.highConfidence : styles.lowConfidence}`}
        tabIndex={0}
        aria-label={explanation}
        aria-describedby={`confidence-${chart.id}`}
      >
        {confidence === "high" ? (
          <BadgeCheck size={17} aria-hidden="true" />
        ) : (
          <BadgeAlert size={17} aria-hidden="true" />
        )}
      </span>
      <span
        className={styles.confidenceTooltip}
        id={`confidence-${chart.id}`}
        role="tooltip"
      >
        {explanation}
      </span>
    </span>
  );
}
