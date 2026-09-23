"use client";

/**
 * The dbt project repository fields: the GitHub picker, an optional branch,
 * and (self-host only) a free-text URL or local path. The eval set runs
 * against this project; SignalPilot clones it for every run.
 */

import type { GitHubInstallation } from "~/lib/types";
import {
  ONBOARDING_PICKER_STYLES,
  RepoPicker,
  type RepoPickerStyles,
  type RepoSelection,
} from "./RepoPicker";

export type ProjectRepoValue = RepoSelection & { ref: string };

export const EMPTY_PROJECT_REPO: ProjectRepoValue = { url: "", installationId: null, repoId: null, ref: "" };

export type ProjectRepoPayload = {
  project_repo_url: string;
  project_repo_installation_id: string | null;
  project_repo_id: number | null;
  project_ref: string;
};

export function projectRepoFromConfig(config: {
  project_repo_url?: string | null;
  project_repo_installation_id?: string | null;
  project_repo_id?: number | null;
  project_ref?: string | null;
}): ProjectRepoValue {
  return {
    url: config.project_repo_url ?? "",
    installationId: config.project_repo_installation_id ?? null,
    repoId: config.project_repo_id ?? null,
    ref: config.project_ref ?? "",
  };
}

/** The four config fields. Installation id and repo id are set together or not at all. */
export function projectRepoPayload(value: ProjectRepoValue): ProjectRepoPayload {
  const paired = Boolean(value.installationId && value.repoId);
  return {
    project_repo_url: value.url.trim(),
    project_repo_installation_id: paired ? value.installationId : null,
    project_repo_id: paired ? value.repoId : null,
    project_ref: value.ref.trim(),
  };
}

/** Cloud mode needs a picked GitHub repository. Self-host also accepts a URL or local path. */
export function projectRepoError(value: ProjectRepoValue, isCloudMode: boolean): string | null {
  if (isCloudMode) {
    return value.installationId && value.repoId && value.url.trim()
      ? null
      : "Select the dbt project repository from a connected GitHub account.";
  }
  return value.url.trim() ? null : "Enter the dbt project repository URL or local path.";
}

export type ProjectRepoFieldsProps = {
  value: ProjectRepoValue;
  onChange: (next: ProjectRepoValue) => void;
  installations: GitHubInstallation[] | undefined;
  installationsLoading: boolean;
  onConnectGitHub: () => void;
  connectingGitHub: boolean;
  isCloudMode: boolean;
  styles?: RepoPickerStyles;
};

export function ProjectRepoFields({
  value,
  onChange,
  installations,
  installationsLoading,
  onConnectGitHub,
  connectingGitHub,
  isCloudMode,
  styles = ONBOARDING_PICKER_STYLES,
}: ProjectRepoFieldsProps) {
  return (
    <div className="ev-project-repo" data-testid="project-repo-fields">
      <RepoPicker
        value={value}
        onChange={(next) => onChange({ ...next, ref: value.ref })}
        installations={installations}
        installationsLoading={installationsLoading}
        onConnectGitHub={onConnectGitHub}
        connectingGitHub={connectingGitHub}
        connectPrompt="Choose the account and grant access to the dbt project the eval set runs against."
        styles={styles}
        testId="project-repo"
      />
      {!isCloudMode && (
        <label className={styles.field}>
          <span className={styles.label}>Repository URL or local path</span>
          <input
            className={styles.control}
            data-testid="project-repo-url"
            value={value.installationId ? "" : value.url}
            disabled={Boolean(value.installationId)}
            onChange={(event) => onChange({ ...value, url: event.target.value, installationId: null, repoId: null })}
            placeholder="https://github.com/org/dbt-project or /eval-projects/northwind"
          />
        </label>
      )}
      <label className={styles.field}>
        <span className={styles.label}>Branch</span>
        <input
          className={styles.control}
          data-testid="project-repo-ref"
          value={value.ref}
          onChange={(event) => onChange({ ...value, ref: event.target.value })}
          placeholder="repository default"
        />
      </label>
    </div>
  );
}
