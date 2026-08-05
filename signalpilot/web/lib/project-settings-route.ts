export function projectSettingsHref(projectId: string | null | undefined) {
  return projectId
    ? `/projects/${encodeURIComponent(projectId)}/settings`
    : "/projects";
}
