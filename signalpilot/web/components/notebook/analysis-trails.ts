export const ANALYSIS_BRANCH_PREFIX = "analysis/";
export const ANALYSIS_NOTEBOOK_RELPATH_PREFIXES = {
  notion: "notebooks/notion/",
  slack: "notebooks/slack/",
} as const;

export function isGeneratedAnalysisTrailNotebook({
  project,
  branch,
  file,
}: {
  project?: string | null;
  branch?: string | null;
  file?: string | null;
}): boolean {
  if (!project || !branch || !file) return false;
  if (!branch.startsWith(ANALYSIS_BRANCH_PREFIX)) return false;

  const normalized = file.replace(/\\/g, "/").replace(/^\/+/, "");
  return Object.entries(ANALYSIS_NOTEBOOK_RELPATH_PREFIXES).some(
    ([source, prefix]) =>
      branch.startsWith(`${ANALYSIS_BRANCH_PREFIX}${source}/`) &&
      normalized.startsWith(prefix),
  );
}

export const ANALYSIS_TRAIL_CONFIG_OVERRIDES = {
  runtime: {
    auto_instantiate: false,
  },
} as const;
