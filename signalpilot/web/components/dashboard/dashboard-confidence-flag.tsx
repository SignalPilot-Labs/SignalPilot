"use client";

import { BadgeAlert, BadgeCheck } from "lucide-react";
import { useRef, useState } from "react";
import { Popover as AriaPopover } from "react-aria-components";

import type { ChartDefinition } from "~/lib/dashboard/contracts";
import {
  chartConfidence,
  confidenceExplanation,
} from "~/lib/dashboard/confidence";

import styles from "./dashboard-runtime.module.css";

export function DashboardConfidenceFlag({ chart }: { chart: ChartDefinition }) {
  const confidence = chartConfidence(chart);
  const explanation = confidenceExplanation(chart);
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  return (
    <>
      <button
        ref={trigger}
        type="button"
        className={`${styles.confidenceFlag} ${confidence === "high" ? styles.highConfidence : styles.lowConfidence}`}
        aria-label={explanation}
        aria-describedby={`confidence-description-${chart.id}`}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
      >
        {confidence === "high" ? (
          <BadgeCheck size={17} aria-hidden="true" />
        ) : (
          <BadgeAlert size={17} aria-hidden="true" />
        )}
      </button>
      <AriaPopover
        className={styles.confidenceTooltip}
        placement="bottom end"
        triggerRef={trigger}
        isOpen={open}
        onOpenChange={setOpen}
        isNonModal
      >
        <div id={`confidence-description-${chart.id}`} role="tooltip">
          {explanation}
        </div>
      </AriaPopover>
    </>
  );
}
