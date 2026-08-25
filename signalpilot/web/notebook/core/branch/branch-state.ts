import { atom } from "jotai";
import { atomWithStorage } from "jotai/utils";
import {
  getGatewayBranchId,
  getGatewayProjectId,
  setGatewayBranchId,
  spApiUrl,
} from "@/core/network/api";
import { getApiHeaders } from "@/core/network/api-headers";
import { store } from "@/core/state/jotai";
import { jotaiJsonStorage } from "@/utils/storage/jotai";

export interface BranchInfo {
  id: string;
  name: string;
  is_default: boolean;
  is_protected: boolean;
  status: string;
  file_count: number;
  created_by: string;
  created_at: number;
  updated_at: number;
  sha?: string;
  date?: string;
  timestamp?: number;
  is_current?: boolean;
  is_remote?: boolean;
  is_local?: boolean;
  is_agent?: boolean;
}

export const gatewayBranchIdAtom = atomWithStorage<string | null>(
  "sp:gateway-branch-id",
  null,
  jotaiJsonStorage,
  { getOnInit: true },
);

export const branchListAtom = atom<BranchInfo[]>([]);
export const branchLoadingAtom = atom(false);

export async function fetchBranches(): Promise<BranchInfo[]> {
  const projectId = getGatewayProjectId();
  if (!projectId) {return [];}

  try {
    const resp = await fetch(spApiUrl("/branches/list"), {
      method: "POST",
      headers: await getApiHeaders(),
    });
    if (!resp.ok) {return [];}
    interface RawBranch {
      name: string;
      is_current?: boolean;
      is_agent?: boolean;
      sha?: string;
      date?: string;
      timestamp?: number;
      is_remote?: boolean;
      is_local?: boolean;
    }
    const data = await resp.json() as { branches?: RawBranch[] };
    const raw = data.branches || [];

    return raw.map((b) => ({
      id: b.name,
      name: b.name,
      is_default: b.is_current || false,
      is_protected: false,
      status: "active",
      file_count: 0,
      created_by: b.is_agent ? "agent" : "local",
      created_at: 0,
      updated_at: 0,
      sha: b.sha || "",
      date: b.date || "",
      timestamp: b.timestamp || 0,
      is_current: b.is_current || false,
      is_remote: b.is_remote || false,
      is_local: b.is_local !== false,
      is_agent: b.is_agent || false,
    }));
  } catch {
    return [];
  }
}

export async function createBranch(name: string, fromBranch?: string): Promise<boolean> {
  const projectId = getGatewayProjectId();
  if (!projectId) {return false;}

  try {
    const resp = await fetch(spApiUrl("/branches/create"), {
      method: "POST",
      headers: await getApiHeaders(),
      body: JSON.stringify({
        name,
        source_branch: fromBranch || getGatewayBranchId() || "main",
      }),
    });
    return resp.ok;
  } catch {
    return false;
  }
}

export async function switchBranch(branchName: string): Promise<boolean> {
  // The workspace store holds every branch; switching just rebinds the
  // session's file system. Saves are revisions, so nothing can be "lost".
  try {
    const resp = await fetch(spApiUrl("/branches/switch"), {
      method: "POST",
      headers: await getApiHeaders(),
      body: JSON.stringify({ branch: branchName }),
    });
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({})) as { error?: string };
      console.error("[Branch] Switch failed:", data.error);
      return false;
    }
  } catch (e) {
    console.error("[Branch] Switch failed:", e);
    return false;
  }

  setGatewayBranchId(branchName);
  store.set(gatewayBranchIdAtom, branchName);
  localStorage.removeItem("sp:file-tree-cache");
  localStorage.removeItem("sp:file-tree-open-state");
  return true;
}
