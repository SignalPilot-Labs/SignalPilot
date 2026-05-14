"use client";

import { useState, useTransition, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import { createDashboard } from "@/lib/dashboards/save-dashboard";

interface NewDashboardModalProps {
  open: boolean;
  onClose: () => void;
}

export function NewDashboardModal({ open, onClose }: NewDashboardModalProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      setName("");
      setDescription("");
      setError(null);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  if (!open) return null;

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    startTransition(async () => {
      const result = await createDashboard({ name, description });
      if (!result.ok) {
        setError(result.error);
        return;
      }
      onClose();
      router.push(`/dashboards/${result.id}`);
    });
  }

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="bg-[var(--color-bg-card)] border border-[var(--color-border)] w-full max-w-md p-6">
        <h2 className="text-[12px] font-medium tracking-[0.15em] uppercase text-[var(--color-text)] mb-4">
          new dashboard
        </h2>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label
              htmlFor="dashboard-name"
              className="block text-[11px] uppercase tracking-[0.15em] text-[var(--color-text-dim)] mb-1"
            >
              name
            </label>
            <input
              ref={inputRef}
              id="dashboard-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Revenue Overview"
              maxLength={120}
              required
              disabled={isPending}
              className="w-full px-3 py-2 bg-[var(--color-bg)] border border-[var(--color-border)] text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-dim)] focus:border-[var(--color-border-hover)] outline-none transition-colors"
            />
          </div>

          <div>
            <label
              htmlFor="dashboard-desc"
              className="block text-[11px] uppercase tracking-[0.15em] text-[var(--color-text-dim)] mb-1"
            >
              description <span className="normal-case">(optional)</span>
            </label>
            <textarea
              id="dashboard-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What is this dashboard for?"
              maxLength={500}
              rows={2}
              disabled={isPending}
              className="w-full px-3 py-2 bg-[var(--color-bg)] border border-[var(--color-border)] text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-dim)] focus:border-[var(--color-border-hover)] outline-none transition-colors resize-none"
            />
          </div>

          {error && (
            <p className="text-[12px] text-[var(--color-error)]">{error}</p>
          )}

          <div className="flex gap-2 justify-end pt-2">
            <button
              type="button"
              onClick={onClose}
              disabled={isPending}
              className="px-4 py-2 text-[12px] uppercase tracking-[0.15em] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] transition-colors"
            >
              cancel
            </button>
            <button
              type="submit"
              disabled={isPending || !name.trim()}
              className="px-4 py-2 text-[12px] uppercase tracking-[0.15em] bg-[var(--color-text)] text-[var(--color-bg)] hover:opacity-90 transition-opacity disabled:opacity-50"
            >
              {isPending ? "creating..." : "create"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
