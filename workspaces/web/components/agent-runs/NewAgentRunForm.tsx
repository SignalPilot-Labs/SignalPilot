"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { saveAgentRun } from "@/lib/agent-runs/save-run";
import {
  FIELD_INPUT_CLASS,
  LABEL_CLASS,
  ERROR_CLASS,
} from "@/components/ui/button-classes";
import { PendingButton } from "@/components/ui/PendingButton";

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
      className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-6 flex flex-col gap-5 max-w-2xl"
    >
      <div className="flex flex-col gap-1">
        <label htmlFor="agent-run-prompt" className={LABEL_CLASS}>
          Prompt
        </label>
        <textarea
          id="agent-run-prompt"
          name="prompt"
          rows={6}
          maxLength={4000}
          disabled={isPending}
          className={`${FIELD_INPUT_CLASS} resize-y`}
          aria-describedby={result && !result.ok ? "agent-run-prompt-error" : undefined}
          aria-invalid={result && !result.ok ? true : undefined}
          placeholder="Describe the task for the agent…"
        />
        {result && !result.ok && (
          <p id="agent-run-prompt-error" role="alert" className={ERROR_CLASS}>
            {result.error}
          </p>
        )}
      </div>

      <PendingButton
        type="submit"
        pending={isPending}
        pendingLabel="Starting…"
        className="w-full"
      >
        Start run
      </PendingButton>
    </form>
  );
}
