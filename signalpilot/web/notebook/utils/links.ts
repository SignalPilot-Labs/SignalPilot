import type { MouseEvent } from "react";
import { getGatewayBranchId, getGatewayProjectId } from "@/core/network/api";
import { KnownQueryParams } from "@/core/constants";
import { navigate } from "@/embed/host-navigate";
import { asURL } from "./url";

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
  const parts: string[] = [];
  if (projectId) {
    parts.push(`project=${encodeURIComponent(projectId)}`);
    if (branchId) {
      parts.push(`branch=${encodeURIComponent(branchId)}`);
    }
  }
  parts.push(`${KnownQueryParams.filePath}=${encodeURIComponent(path)}`);
  navigate(asURL(`?${parts.join("&")}`).toString());
}
