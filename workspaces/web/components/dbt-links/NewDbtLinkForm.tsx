"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { saveDbtLinkNativeUpload } from "@/lib/dbt-links/save-link";
import {
  FIELD_INPUT_CLASS,
  PRIMARY_BTN_CLASS,
  LABEL_CLASS,
  ERROR_CLASS,
} from "@/components/ui/button-classes";

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
      className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-6 flex flex-col gap-5 max-w-2xl"
    >
      <div className="flex flex-col gap-1">
        <label htmlFor="dbt-link-name" className={LABEL_CLASS}>
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
          className={FIELD_INPUT_CLASS}
          aria-describedby={nameError ? "dbt-link-name-error" : undefined}
          aria-invalid={nameError ? true : undefined}
        />
        {nameError && (
          <p id="dbt-link-name-error" role="alert" className={ERROR_CLASS}>
            {nameError}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="dbt-link-file" className={LABEL_CLASS}>
          dbt project archive (.tar.gz)
        </label>
        <input
          id="dbt-link-file"
          type="file"
          accept=".tar.gz,.tgz,application/gzip"
          disabled={isPending}
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          className={FIELD_INPUT_CLASS}
          aria-describedby={fileError ? "dbt-link-file-error" : undefined}
          aria-invalid={fileError ? true : undefined}
        />
        {fileError && (
          <p id="dbt-link-file-error" role="alert" className={ERROR_CLASS}>
            {fileError}
          </p>
        )}
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
        className={`${PRIMARY_BTN_CLASS} w-full`}
      >
        {isPending ? "Uploading…" : "Upload"}
      </button>
    </form>
  );
}
