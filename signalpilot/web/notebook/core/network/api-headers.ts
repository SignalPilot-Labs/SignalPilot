import { getGatewayBranchId, getGatewayProjectId } from "@/core/network/api";
import { getSpServerToken } from "@/core/meta/globals";
import { getRuntimeManager } from "@/core/runtime/config";

/**
 * Build standard API headers for all backend calls.
 * Includes server token, gateway project/branch IDs, and runtime
 * session headers (Authorization, Sp-Session-Id) when available.
 */
export async function getApiHeaders(): Promise<Record<string, string>> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };

  const token = getSpServerToken();
  if (token) {
    headers["Sp-Server-Token"] = token;
  }

  try {
    const rm = getRuntimeManager();
    Object.assign(headers, await rm.headers());
  } catch { /* runtime not ready yet */ }

  const projectId = getGatewayProjectId();
  if (projectId) {
    headers["X-Gateway-Project-Id"] = projectId;
    const branchId = getGatewayBranchId();
    if (branchId) {
      headers["X-Gateway-Branch-Id"] = branchId;
    }
  }

  return headers;
}
