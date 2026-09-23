/** Draft state, validation, and the PUT payload for the eval onboarding wizard. */

import type { EvalConfig } from "~/lib/api";
import {
  projectRepoError,
  projectRepoFromConfig,
  projectRepoPayload,
  type ProjectRepoValue,
} from "./ProjectRepoFields";

export type Draft = {
  repo_url: string;
  repo_installation_id: string | null;
  repo_id: number | null;
  project: ProjectRepoValue;
  model: string;
  max_tasks: number;
  prompt_preamble: string;
  connection: string;
  notify_emails: string;
  autorun_on_knowledge_add: boolean;
};

export type SourceKind = "public" | "private" | "mounted";

export type EvalConfigPayload = Omit<EvalConfig, "enabled" | "runner_image">;

export function initialDraft(config: EvalConfig): Draft {
  return {
    repo_url: config.repo_url ?? "",
    repo_installation_id: config.repo_installation_id ?? null,
    repo_id: config.repo_id ?? null,
    project: projectRepoFromConfig(config),
    model: config.model || "sonnet",
    max_tasks: config.max_tasks ?? 0,
    prompt_preamble: config.prompt_preamble ?? "",
    connection: config.connection ?? "",
    notify_emails: (config.notify_emails ?? []).join(", "),
    autorun_on_knowledge_add: config.autorun_on_knowledge_add ?? false,
  };
}

export function initialSourceKind(config: EvalConfig): SourceKind {
  if (config.repo_installation_id) return "private";
  if (config.repo_url?.startsWith("/eval-projects/")) return "mounted";
  return "public";
}

export function sourceError(value: string): string | null {
  const source = value.trim();
  if (!source) return "Enter an eval repository.";
  if (source.startsWith("/eval-projects/")) {
    const segments = source.slice("/eval-projects/".length).split("/");
    if (segments.every((segment) => segment && segment !== "." && segment !== "..")) return null;
    return "Use a project path without empty, current-directory, or parent-directory segments.";
  }

  try {
    const url = new URL(source);
    if (url.protocol === "https:" && url.hostname === "github.com" && !url.username && !url.password) return null;
  } catch {
    // The mounted-path format is checked before URL parsing.
  }
  return "Use a GitHub HTTPS URL or a path under /eval-projects.";
}

export function emailError(value: string): string | null {
  const addresses = value.split(",").map((email) => email.trim()).filter(Boolean);
  const invalid = addresses.find((email) => !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email));
  return invalid ? `Check the email address: ${invalid}` : null;
}

export function sourceStepError(draft: Draft, sourceKind: SourceKind): string | null {
  if (sourceKind === "private" && (!draft.repo_installation_id || !draft.repo_id)) {
    return "Select a repository from a connected GitHub account.";
  }
  return sourceError(draft.repo_url);
}

export function runtimeStepError(draft: Draft): string | null {
  if (!draft.connection) return "Select the warehouse connection used for grading.";
  if (draft.max_tasks < 0 || draft.max_tasks > 200) return "Max tasks must be between 0 and 200.";
  return null;
}

export function draftError(draft: Draft, sourceKind: SourceKind, isCloudMode: boolean): string | null {
  return sourceStepError(draft, sourceKind)
    || projectRepoError(draft.project, isCloudMode)
    || runtimeStepError(draft)
    || emailError(draft.notify_emails);
}

export function draftPayload(draft: Draft, sourceKind: SourceKind): EvalConfigPayload {
  return {
    repo_url: draft.repo_url.trim(),
    repo_installation_id: sourceKind === "private" ? draft.repo_installation_id : null,
    repo_id: sourceKind === "private" ? draft.repo_id : null,
    ...projectRepoPayload(draft.project),
    model: draft.model,
    max_tasks: draft.max_tasks,
    prompt_preamble: draft.prompt_preamble.trim(),
    connection: draft.connection,
    autorun_on_knowledge_add: draft.autorun_on_knowledge_add,
    notify_emails: draft.notify_emails.split(",").map((email) => email.trim()).filter(Boolean),
  };
}
