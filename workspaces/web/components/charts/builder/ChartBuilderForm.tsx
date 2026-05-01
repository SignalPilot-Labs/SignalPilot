"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { CHART_TYPES, type ChartType } from "@/lib/charts/types";
import { ChartTypeSelect } from "@/components/charts/builder/ChartTypeSelect";
import { saveChartDefinition } from "@/lib/charts/save-chart";
import {
  FIELD_INPUT_CLASS,
  PRIMARY_BTN_CLASS,
  LABEL_CLASS,
  ERROR_CLASS,
} from "@/components/ui/button-classes";

type SaveResult = { ok: false; error: string } | null;

export function ChartBuilderForm() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [type, setType] = useState<ChartType>(CHART_TYPES[0]);
  const [sql, setSql] = useState("");
  const [nameError, setNameError] = useState<string | null>(null);
  const [result, setResult] = useState<SaveResult>(null);
  const [isPending, startTransition] = useTransition();

  function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setResult(null);

    const trimmedName = name.trim();
    if (trimmedName.length === 0) {
      setNameError("Name is required.");
      return;
    }
    setNameError(null);

    startTransition(async () => {
      const res = await saveChartDefinition({ name: trimmedName, type, sql: sql.trim() });
      if (res.ok) {
        router.push(`/charts/${res.id}`);
      } else {
        setResult(res);
      }
    });
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-6 flex flex-col gap-5 max-w-2xl"
    >
      <div className="flex flex-col gap-1">
        <label htmlFor="chart-name" className={LABEL_CLASS}>
          Name
        </label>
        <input
          id="chart-name"
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Monthly revenue"
          maxLength={120}
          disabled={isPending}
          className={FIELD_INPUT_CLASS}
          aria-describedby={nameError ? "name-error" : undefined}
          aria-invalid={nameError ? true : undefined}
        />
        {nameError && (
          <p id="name-error" role="alert" className={ERROR_CLASS}>
            {nameError}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="chart-type" className={LABEL_CLASS}>
          Chart type
        </label>
        <ChartTypeSelect value={type} onChange={setType} disabled={isPending} />
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="chart-sql" className={LABEL_CLASS}>
          SQL query
        </label>
        <textarea
          id="chart-sql"
          value={sql}
          onChange={(e) => setSql(e.target.value)}
          placeholder="SELECT ..."
          rows={8}
          maxLength={4000}
          disabled={isPending}
          className={`${FIELD_INPUT_CLASS} resize-y`}
        />
      </div>

      {result && !result.ok && (
        <p role="alert" className={ERROR_CLASS}>
          {result.error}
        </p>
      )}

      <button
        type="submit"
        disabled={isPending}
        aria-busy={isPending}
        className={PRIMARY_BTN_CLASS}
      >
        {isPending ? "Saving…" : "Save"}
      </button>
    </form>
  );
}
