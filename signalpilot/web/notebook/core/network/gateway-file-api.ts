/**
 * File operations against the gateway's notebook-files compat router.
 *
 * The gateway serves the notebook editor's file plane directly from the
 * S3-backed workspace store at
 * `/api/workspace-projects/{projectId}/nb-files/*` — same request/response
 * JSON shapes as the sandbox `/api/files/*` endpoints, but with NO notebook
 * session or sandbox required. This is what lets the file tree and file
 * editors work before any kernel exists.
 *
 * Base URL + auth mirror how the editor already reaches the gateway:
 * - Cloud (embedded editor): NotebookConfig.gatewayUrl + Clerk JWT from
 *   config.getToken(), sent as `Authorization: Bearer`.
 * - Local/standalone: gatewayUrlAtom + gatewayApiKeyAtom; JWTs (contain
 *   dots) go as Bearer, `sp_` keys as `X-API-Key`.
 *
 * The branch always travels as a `?branch=` query parameter (branch names
 * may contain '/').
 */

import { Logger } from "@/utils/Logger";
import { gatewayApiKeyAtom, gatewayUrlAtom } from "@/core/meta/state";
import { getCurrentStore } from "@/core/state/store-binding";
import { getGatewayBranchId, getGatewayProjectId } from "./api";
import type {
  FileCreateInput,
  FileCreateResponse,
  FileCopyRequest,
  FileCopyResponse,
  FileDeleteRequest,
  FileDeleteResponse,
  FileDetailsRequest,
  FileDetailsResponse,
  FileListRequest,
  FileListResponse,
  FileMoveRequest,
  FileMoveResponse,
  FileSearchRequest,
  FileSearchResponse,
  FileUpdateRequest,
  FileUpdateResponse,
} from "./types";

/**
 * True when a gateway workspace project is active — the signal that file
 * operations should go straight to the gateway store instead of the sandbox
 * proxy path (which requires a running notebook session).
 */
export function hasGatewayFilePlane(): boolean {
  return Boolean(getGatewayProjectId());
}

function keyHeaders(key: string): Record<string, string> {
  if (!key) {
    return {};
  }
  // JWTs contain dots (header.payload.signature); sp_ keys don't.
  if (key.includes(".")) {
    return { Authorization: `Bearer ${key}` };
  }
  return { "X-API-Key": key };
}

async function resolveGateway(): Promise<{
  base: string;
  headers: Record<string, string>;
}> {
  // Cloud/embedded: NotebookConfig carries the gateway URL and a fresh Clerk
  // token per request. Dynamic import mirrors api-call.ts (the provider lives
  // outside the notebook package).
  try {
    const { getNotebookConfig } = await import(
      "../../../components/notebook/notebook-context"
    );
    const config = getNotebookConfig();
    const base = (config.gatewayUrl ?? "").replace(/\/$/, "");
    if (base) {
      const token = await config.getToken();
      if (token) {
        return { base, headers: { Authorization: `Bearer ${token}` } };
      }
      return { base, headers: keyHeaders(config.apiKey ?? "") };
    }
  } catch {
    /* NotebookConfig not set — standalone mode, fall through */
  }

  const store = getCurrentStore();
  const base =
    store.get(gatewayUrlAtom) ||
    (typeof localStorage !== "undefined"
      ? localStorage.getItem("sp:gateway-url")
      : null) ||
    "http://localhost:3300";
  const key =
    store.get(gatewayApiKeyAtom) ||
    (typeof localStorage !== "undefined"
      ? localStorage.getItem("sp:api-key")
      : null) ||
    "";
  return { base: base.replace(/\/$/, ""), headers: keyHeaders(key) };
}

async function nbFilesCall<T>(
  op: string,
  body: unknown,
  opts?: { formData?: FormData },
): Promise<T> {
  const projectId = getGatewayProjectId();
  if (!projectId) {
    throw new Error("No gateway project set — cannot reach the gateway file plane");
  }
  const branch = getGatewayBranchId() || "main";
  const { base, headers } = await resolveGateway();
  const url = `${base}/api/workspace-projects/${encodeURIComponent(
    projectId,
  )}/nb-files/${op}?branch=${encodeURIComponent(branch)}`;

  const init: RequestInit = opts?.formData
    ? // Let the browser set the multipart Content-Type with boundary.
      { method: "POST", headers, body: opts.formData }
    : {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify(body ?? {}),
      };

  const response = await fetch(url, init).catch((error) => {
    Logger.error(`Error requesting ${url}`, error);
    throw error;
  });

  const isJson = response.headers
    .get("Content-Type")
    ?.startsWith("application/json");
  if (!response.ok) {
    const errorBody = isJson ? await response.json() : await response.text();
    throw new Error(response.statusText, { cause: errorBody });
  }
  if (isJson) {
    return response.json() as Promise<T>;
  }
  return response.text() as unknown as Promise<T>;
}

export function gwListFiles(request: FileListRequest): Promise<FileListResponse> {
  return nbFilesCall<FileListResponse>("list_files", request);
}

export function gwFileDetails(
  request: FileDetailsRequest,
): Promise<FileDetailsResponse> {
  return nbFilesCall<FileDetailsResponse>("file_details", request);
}

export function gwCreateFileOrFolder(
  request: FileCreateInput,
): Promise<FileCreateResponse> {
  const formData = new FormData();
  formData.append("path", request.path);
  formData.append("type", request.type);
  formData.append("name", request.name);
  if (request.file) {
    formData.append("file", request.file, request.name);
  }
  return nbFilesCall<FileCreateResponse>("create", undefined, { formData });
}

export function gwDeleteFileOrFolder(
  request: FileDeleteRequest,
): Promise<FileDeleteResponse> {
  return nbFilesCall<FileDeleteResponse>("delete", request);
}

export function gwCopyFileOrFolder(
  request: FileCopyRequest,
): Promise<FileCopyResponse> {
  return nbFilesCall<FileCopyResponse>("copy", request);
}

export function gwRenameFileOrFolder(
  request: FileMoveRequest,
): Promise<FileMoveResponse> {
  return nbFilesCall<FileMoveResponse>("move", request);
}

export function gwUpdateFile(
  request: FileUpdateRequest,
): Promise<FileUpdateResponse> {
  return nbFilesCall<FileUpdateResponse>("update", request);
}

export function gwSearchFiles(
  request: FileSearchRequest,
): Promise<FileSearchResponse> {
  return nbFilesCall<FileSearchResponse>("search", request);
}
