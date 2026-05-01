"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { saveDbtLinkNativeUpload } from "@/lib/dbt-links/save-link";

type SaveResult = { ok: false; error: string } | null;

export function NewDbtLinkForm() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [nameError, setNameError] = useState<string | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
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

    if (!file) {
      setFileError("File is required.");
      return;
    }
    setFileError(null);

    startTransition(async () => {
      const fd = new FormData();
      fd.append("name", trimmedName);
      fd.append("file", file);

      const res = await saveDbtLinkNativeUpload(fd);
      if (res.ok) {
        router.push(`/dbt-links/${res.id}`);
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
      <h1 className="text-2xl font-semibold text-fg">New dbt link</h1>

      <div className="flex flex-col gap-1">
        <label htmlFor="dbt-link-name" className="text-sm font-medium text-fg">
          Name
        </label>
        <input
          id="dbt-link-name"
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. My dbt project"
          maxLength={120}
          disabled={isPending}
          className="rounded-control border border-border bg-bg px-3 py-2 text-sm text-fg placeholder:text-muted focus:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50"
          aria-describedby={nameError ? "dbt-link-name-error" : undefined}
          aria-invalid={nameError ? true : undefined}
        />
        {nameError && (
          <p id="dbt-link-name-error" role="alert" className="text-xs text-danger-fg">
            {nameError}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="dbt-link-file" className="text-sm font-medium text-fg">
          dbt project archive (.tar.gz)
        </label>
        <input
          id="dbt-link-file"
          type="file"
          accept=".tar.gz,.tgz,application/gzip"
          disabled={isPending}
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          className="rounded-control border border-border bg-bg px-3 py-2 text-sm text-fg focus:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50"
          aria-describedby={fileError ? "dbt-link-file-error" : undefined}
          aria-invalid={fileError ? true : undefined}
        />
        {fileError && (
          <p id="dbt-link-file-error" role="alert" className="text-xs text-danger-fg">
            {fileError}
          </p>
        )}
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
        {isPending ? "Uploading…" : "Upload"}
      </button>
    </form>
  );
}
