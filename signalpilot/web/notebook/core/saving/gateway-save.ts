import { Logger } from "@/utils/Logger";

/**
 * Kernel-free notebook persistence.
 *
 * When no runtime session exists (sessionless boot), saves serialize the
 * cells client-side and write the .py straight to the gateway workspace
 * store. The next kernel to start hydrates from the store, so what you see
 * is what runs. Once a kernel is connected, the server-side save path takes
 * over and re-serializes canonically (full dataflow signatures).
 */

export interface GatewaySaveCell {
  code: string;
  name: string;
  config: {
    hide_code?: boolean | null;
    disabled?: boolean | null;
    column?: number | null;
  };
}

/** Whether the sessionless gateway save path is available for this mount. */
export async function canSaveViaGateway(): Promise<boolean> {
  try {
    const { tryGetNotebookConfig } = await import(
      "../../../components/notebook/notebook-context"
    );
    const config = tryGetNotebookConfig();
    return Boolean(config?.project && config.gatewayUrl);
  } catch {
    return false;
  }
}

export async function saveNotebookViaGateway(
  filename: string,
  cells: GatewaySaveCell[],
): Promise<void> {
  const { tryGetNotebookConfig } = await import(
    "../../../components/notebook/notebook-context"
  );
  const config = tryGetNotebookConfig();
  if (!config?.project || !config.gatewayUrl) {
    throw new Error("Gateway save unavailable: no project workspace bound");
  }

  const { serializeNotebookPy } = await import("@/core/notebook-file/serialize");
  const contents = serializeNotebookPy(
    cells.map((c) => ({
      code: c.code,
      name: c.name,
      config: {
        hide_code: c.config.hide_code ?? undefined,
        disabled: c.config.disabled ?? undefined,
        column: c.config.column ?? undefined,
      },
    })),
  );

  const branch = config.branch || "main";
  const base = config.gatewayUrl.replace(/\/$/, "");
  const token = await config.getToken();
  const url = `${base}/api/workspace-projects/${encodeURIComponent(config.project)}/files/${filename
    .split("/")
    .map(encodeURIComponent)
    .join("/")}?branch=${encodeURIComponent(branch)}`;

  const response = await fetch(url, {
    method: "PUT",
    headers: {
      "Content-Type": "text/plain",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: contents,
  });
  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    Logger.error("Gateway save failed", response.status, detail);
    throw new Error(`Failed to save notebook (${response.status})`);
  }
}
