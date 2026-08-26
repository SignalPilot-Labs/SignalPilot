import type { MouseEvent } from "react";
import { dbtProjectDirAtom } from "@/components/editor/dbt/use-dbt";
import { getGatewayBranchId, getGatewayProjectId } from "@/core/network/api";
import { KnownQueryParams } from "@/core/constants";
import { store } from "@/core/state/jotai";
import { navigate } from "@/embed/host-navigate";
import { buildProjectEditorNavigationHref } from "~/lib/project-editor-link";
import { asURL } from "./url";

export {
  buildProjectEditorHref,
  type ProjectEditorLink,
} from "~/lib/project-editor-link";

export function toProjectRelativeFilePath(path: string): string {
  const normalizedPath = path.replace(/\\/g, "/");
  const projectDirectory = store.get(dbtProjectDirAtom)?.replace(/\\/g, "/").replace(/\/$/, "");
  if (
    projectDirectory &&
    normalizedPath.startsWith(`${projectDirectory}/`)
  ) {
    return normalizedPath.slice(projectDirectory.length + 1);
  }

  const syncMarker = "/.sp/projects/";
  const syncIndex = normalizedPath.indexOf(syncMarker);
  if (syncIndex !== -1) {
    const segments = normalizedPath
      .slice(syncIndex + syncMarker.length)
      .split("/");
    if (segments.length > 2) {
      return segments.slice(2).join("/");
    }
  }
  return normalizedPath.replace(/^\/+/, "");
}

/**
 * Returns true for a plain left-click with no modifier keys held.
 * Use this to decide whether to intercept an anchor click for in-page SPA
 * navigation while preserving native middle-click / Cmd-click → new tab.
 */
export function isPlainLeftClick(e: MouseEvent): boolean {
  return (
    e.button === 0 &&
    !e.ctrlKey &&
    !e.metaKey &&
    !e.shiftKey &&
    !e.altKey
  );
}

/**
 * Open a notebook in the current tab via in-page SPA navigation.
 * In embed mode, delegates to the host router.
 * @param path - The path to the notebook.
 */
export function openNotebook(path: string): void {
  const projectId = getGatewayProjectId();
  const branchId = getGatewayBranchId();
  const filePath = projectId ? toProjectRelativeFilePath(path) : path;
  if (projectId) {
    navigate(
      buildProjectEditorNavigationHref({
        currentHref: window.location.href,
        project: projectId,
        branch: branchId || "main",
        file: filePath,
      }),
    );
    return;
  }

  const parts: string[] = [];
  parts.push(`${KnownQueryParams.filePath}=${encodeURIComponent(filePath)}`);
  navigate(asURL(`?${parts.join("&")}`).toString());
}
