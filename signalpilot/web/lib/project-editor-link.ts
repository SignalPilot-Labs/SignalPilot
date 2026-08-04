export interface ProjectEditorLink {
  project: string;
  branch: string;
  file: string;
}

export interface ProjectEditorNavigationLink extends ProjectEditorLink {
  currentHref: string;
}

/**
 * Build the durable, authenticated URL for a project-backed editor.
 *
 * Runtime session IDs and pod URLs are deliberately not accepted here.
 */
export function buildProjectEditorHref({
  project,
  branch,
  file,
}: ProjectEditorLink): string {
  const normalizedFile = file.replace(/\\/g, "/");
  if (
    !project ||
    !branch ||
    !normalizedFile ||
    normalizedFile.startsWith("/") ||
    /^[A-Za-z]:\//.test(normalizedFile) ||
    normalizedFile.split("/").includes("..")
  ) {
    throw new Error("Project editor links require a project-relative file");
  }

  const params = new URLSearchParams({
    project,
    branch,
    file: normalizedFile,
  });
  return `/projects?${params.toString()}`;
}

/**
 * Build an in-editor navigation URL without leaking the runtime proxy path
 * into the browser address bar.
 *
 * The notebook runtime sets document.baseURI to /notebook/<session-id>/ for
 * API and asset resolution. File navigation must instead stay on the visible
 * Next.js editor surface: /projects or the exact /notebook fullscreen route.
 */
export function buildProjectEditorNavigationHref({
  currentHref,
  project,
  branch,
  file,
}: ProjectEditorNavigationLink): string {
  const current = new URL(currentHref);
  const canonical = new URL(
    buildProjectEditorHref({ project, branch, file }),
    current.origin,
  );

  if (current.pathname === "/notebook") {
    canonical.pathname = "/notebook";
  }

  return canonical.toString();
}
