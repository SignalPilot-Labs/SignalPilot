"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { saveAgentRun } from "@/lib/agent-runs/save-run";

type SaveResult = { ok: false; error: string } | null;

export function NewAgentRunForm() {
  const router = useRouter();
  const [result, setResult] = useState<SaveResult>(null);
  const [isPending, startTransition] = useTransition();

  function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setResult(null);

    const formData = new FormData(e.currentTarget);
    const raw = formData.get("prompt");
    const prompt = typeof raw === "string" ? raw.trim() : "";

    if (prompt.length === 0) {
      setResult({ ok: false, error: "Prompt is required." });
      return;
    }
    if (prompt.length > 4000) {
      setResult({ ok: false, error: "Prompt must be 4000 characters or fewer." });
      return;
    }

    startTransition(async () => {
      const fd = new FormData();
      fd.append("prompt", prompt);

      const res = await saveAgentRun(fd);
      if (res.ok) {
        router.push(`/agent-runs/${res.id}`);
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
      <h1 className="text-2xl font-semibold text-fg">New agent run</h1>

      <div className="flex flex-col gap-1">
        <label htmlFor="agent-run-prompt" className="text-sm font-medium text-fg">
          Prompt
        </label>
        <textarea
          id="agent-run-prompt"
          name="prompt"
          rows={6}
          maxLength={4000}
          disabled={isPending}
          className="rounded-control border border-border bg-bg px-3 py-2 text-sm text-fg placeholder:text-muted focus:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50 resize-y"
          aria-describedby={result && !result.ok ? "agent-run-prompt-error" : undefined}
          aria-invalid={result && !result.ok ? true : undefined}
          placeholder="Describe the task for the agent…"
        />
        {result && !result.ok && (
          <p id="agent-run-prompt-error" role="alert" className="text-sm text-danger-fg">
            {result.error}
          </p>
        )}
      </div>

      <button
        type="submit"
        disabled={isPending}
        className="self-start rounded-control bg-accent px-4 py-2 text-sm font-medium text-white hover:opacity-90 transition-opacity disabled:opacity-50"
      >
        {isPending ? "Starting…" : "Start run"}
      </button>
    </form>
  );
}
