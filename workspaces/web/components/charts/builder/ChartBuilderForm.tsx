"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { CHART_TYPES, type ChartType } from "@/lib/charts/types";
import { ChartTypeSelect } from "@/components/charts/builder/ChartTypeSelect";
import { saveChartDefinition } from "@/lib/charts/save-chart";

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
      className="rounded-card border border-border bg-surface p-6 shadow-card flex flex-col gap-5 max-w-2xl"
    >
      <h1 className="text-2xl font-semibold text-fg">New chart</h1>

      <div className="flex flex-col gap-1">
        <label htmlFor="chart-name" className="text-sm font-medium text-fg">
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
          className="rounded-control border border-border bg-bg px-3 py-2 text-sm text-fg placeholder:text-muted focus:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50"
          aria-describedby={nameError ? "name-error" : undefined}
          aria-invalid={nameError ? true : undefined}
        />
        {nameError && (
          <p id="name-error" role="alert" className="text-xs text-danger-fg">
            {nameError}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="chart-type" className="text-sm font-medium text-fg">
          Chart type
        </label>
        <ChartTypeSelect value={type} onChange={setType} disabled={isPending} />
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="chart-sql" className="text-sm font-medium text-fg">
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
          className="rounded-control border border-border bg-bg px-3 py-2 text-sm text-fg font-mono placeholder:text-muted focus:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50 resize-y"
        />
      </div>

      {result && !result.ok && (
        <p role="alert" className="text-sm text-danger-fg">
          {result.error}
        </p>
      )}

      <button
        type="submit"
        disabled={isPending}
        className="self-start rounded-control bg-accent px-4 py-2 text-sm font-medium text-white hover:opacity-90 transition-opacity disabled:opacity-50"
      >
        {isPending ? "Saving…" : "Save"}
      </button>
    </form>
  );
}
