"use client";

import { useState, useTransition, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import { uploadNotebook } from "@/lib/api";
import { invalidateNotebooks } from "@/lib/hooks/use-gateway-data";

const MAX_TAGS = 20;
const MAX_TAG_LENGTH = 64;

interface NotebookUploadModalProps {
  open: boolean;
  onClose: () => void;
}

export function NotebookUploadModal({ open, onClose }: NotebookUploadModalProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tags, setTags] = useState<string[]>([]);
  const [tagInput, setTagInput] = useState("");
  const [isPending, startTransition] = useTransition();
  const router = useRouter();
  const nameRef = useRef<HTMLInputElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      setName("");
      setDescription("");
      setFile(null);
      setError(null);
      setTags([]);
      setTagInput("");
      if (fileRef.current) fileRef.current.value = "";
      setTimeout(() => nameRef.current?.focus(), 50);
    }
  }, [open]);

  // Escape key closes the modal — must be before the early return (rules of hooks)
  useEffect(() => {
    if (!open || isPending) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        onClose();
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open, onClose, isPending]);

  if (!open) return null;

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const picked = e.target.files?.[0] ?? null;
    setFile(picked);
    // Auto-populate name from filename if name is empty
    if (picked && !name.trim()) {
      const baseName = picked.name.replace(/\.ipynb$/i, "").replace(/[-_]/g, " ");
      setName(baseName);
    }
  }

  function handleTagKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      const trimmed = tagInput.trim().replace(/,+$/, "");
      if (!trimmed) return;
      if (trimmed.length > MAX_TAG_LENGTH) {
        setError(`Tag must be ${MAX_TAG_LENGTH} characters or fewer.`);
        return;
      }
      if (tags.length >= MAX_TAGS) {
        setError(`Maximum ${MAX_TAGS} tags allowed.`);
        return;
      }
      setError(null);
      if (!tags.includes(trimmed)) {
        setTags((prev) => [...prev, trimmed]);
      }
      setTagInput("");
    }
  }

  function removeTag(tag: string) {
    setTags((prev) => prev.filter((t) => t !== tag));
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) {
      setError("Please select a .ipynb file.");
      return;
    }
    setError(null);

    startTransition(async () => {
      try {
        const content = await new Promise<string>((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(reader.result as string);
          reader.onerror = () => reject(new Error("Failed to read file."));
          reader.readAsText(file);
        });

        const info = await uploadNotebook({
          name: name.trim(),
          content,
          description: description.trim(),
          tags,
        });

        await invalidateNotebooks();
        onClose();
        router.push(`/notebooks/${info.id}`);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Upload failed.");
      }
    });
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="notebook-upload-title"
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="bg-[var(--color-bg-card)] border border-[var(--color-border)] w-full max-w-md p-6">
        <h2 id="notebook-upload-title" className="text-[12px] font-medium tracking-[0.15em] uppercase text-[var(--color-text)] mb-4">
          upload notebook
        </h2>

        <form onSubmit={handleSubmit} className="space-y-4">
          {/* File picker */}
          <div>
            <label
              htmlFor="notebook-file"
              className="block text-[11px] uppercase tracking-[0.15em] text-[var(--color-text-dim)] mb-1"
            >
              notebook file (.ipynb)
            </label>
            <input
              ref={fileRef}
              id="notebook-file"
              type="file"
              accept=".ipynb,application/json"
              onChange={handleFileChange}
              required
              disabled={isPending}
              className="w-full text-[12px] text-[var(--color-text-muted)] file:mr-3 file:px-3 file:py-1.5 file:border file:border-[var(--color-border)] file:bg-[var(--color-bg)] file:text-[11px] file:text-[var(--color-text-dim)] file:uppercase file:tracking-wider file:cursor-pointer hover:file:border-[var(--color-border-hover)] file:transition-colors"
            />
          </div>

          {/* Name */}
          <div>
            <label
              htmlFor="notebook-name"
              className="block text-[11px] uppercase tracking-[0.15em] text-[var(--color-text-dim)] mb-1"
            >
              name
            </label>
            <input
              ref={nameRef}
              id="notebook-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Revenue Analysis"
              maxLength={120}
              required
              disabled={isPending}
              className="w-full px-3 py-2 bg-[var(--color-bg)] border border-[var(--color-border)] text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-dim)] focus:border-[var(--color-border-hover)] outline-none transition-colors"
            />
          </div>

          {/* Description */}
          <div>
            <label
              htmlFor="notebook-desc"
              className="block text-[11px] uppercase tracking-[0.15em] text-[var(--color-text-dim)] mb-1"
            >
              description <span className="normal-case">(optional)</span>
            </label>
            <textarea
              id="notebook-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What does this notebook do?"
              maxLength={500}
              rows={2}
              disabled={isPending}
              className="w-full px-3 py-2 bg-[var(--color-bg)] border border-[var(--color-border)] text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-dim)] focus:border-[var(--color-border-hover)] outline-none transition-colors resize-none"
            />
          </div>

          {/* Tags */}
          <div>
            <label
              htmlFor="notebook-tags"
              className="block text-[11px] uppercase tracking-[0.15em] text-[var(--color-text-dim)] mb-1"
            >
              tags <span className="normal-case">(optional)</span>
            </label>
            {tags.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mb-2">
                {tags.map((tag) => (
                  <span
                    key={tag}
                    className="inline-flex items-center gap-1 px-2 py-0.5 border border-[var(--color-border)] bg-[var(--color-bg)] text-[10px] font-mono tracking-wider text-[var(--color-text-dim)]"
                  >
                    {tag}
                    <button
                      type="button"
                      onClick={() => removeTag(tag)}
                      disabled={isPending}
                      aria-label={`Remove tag ${tag}`}
                      className="text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors leading-none"
                    >
                      &times;
                    </button>
                  </span>
                ))}
              </div>
            )}
            <input
              id="notebook-tags"
              type="text"
              value={tagInput}
              onChange={(e) => setTagInput(e.target.value)}
              onKeyDown={handleTagKeyDown}
              placeholder="Type and press Enter"
              disabled={isPending || tags.length >= MAX_TAGS}
              className="w-full px-3 py-2 bg-[var(--color-bg)] border border-[var(--color-border)] text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-dim)] focus:border-[var(--color-border-hover)] outline-none transition-colors disabled:opacity-50"
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
              disabled={isPending || !name.trim() || !file}
              className="px-4 py-2 text-[12px] uppercase tracking-[0.15em] bg-[var(--color-text)] text-[var(--color-bg)] hover:opacity-90 transition-opacity disabled:opacity-50"
            >
              {isPending ? "uploading..." : "upload"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
