import "server-only";

import { getServerEnv } from "@/lib/env";
import { getCloudJwt } from "@/lib/auth/get-token";
import { ApiError, ChartListResponse, ChartResponse, ChartRunResponse } from "@/lib/api/types";

interface ChartRunBody {
  force?: boolean;
  params?: Record<string, unknown>;
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const env = getServerEnv();
  const url = `${env.apiUrl}${path}`;
  const headers = new Headers(init?.headers);

  let token: string;
  if (env.mode === "cloud") {
    token = await getCloudJwt();
  } else {
    token = env.localApiKey;
  }
  headers.set("Authorization", `Bearer ${token}`);
  headers.set("Content-Type", "application/json");

  const response = await fetch(url, {
    ...init,
    headers,
    cache: "no-store",
  });

  if (!response.ok) {
    let code = "api_error";
    let message = `API request failed: ${response.status} ${response.statusText}`;
    try {
      const body = (await response.json()) as { detail?: string | { code?: string; message?: string } };
      if (typeof body.detail === "string") {
        message = body.detail;
      } else if (body.detail && typeof body.detail === "object") {
        code = body.detail.code ?? code;
        message = body.detail.message ?? message;
      }
    } catch {
      // ignore JSON parse errors; use defaults
    }
    throw new ApiError(response.status, code, message);
  }

  return response.json() as Promise<T>;
}

export async function listCharts(workspaceId: string): Promise<ChartListResponse> {
  return apiFetch<ChartListResponse>(
    `/v1/charts?workspace=${encodeURIComponent(workspaceId)}`
  );
}

export async function getChart(chartId: string): Promise<ChartResponse> {
  return apiFetch<ChartResponse>(`/v1/charts/${encodeURIComponent(chartId)}`);
}

export async function runChart(chartId: string, body?: ChartRunBody): Promise<ChartRunResponse> {
  return apiFetch<ChartRunResponse>(`/v1/charts/${encodeURIComponent(chartId)}/run`, {
    method: "POST",
    body: JSON.stringify(body ?? {}),
  });
}
