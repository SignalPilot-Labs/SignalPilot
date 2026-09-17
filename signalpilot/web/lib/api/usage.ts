// Usage analytics: organization-wide (admins) and personal usage windows.

import { request } from "./client";
import type { MyUsageResponse, OrgUsageResponse } from "../types";

export type UsageDays = 7 | 30 | 90;

export const getOrgUsage = (days: UsageDays = 30) =>
  request<OrgUsageResponse>(`/api/usage/org?days=${days}`);

export const getMyUsage = (days: UsageDays = 30) =>
  request<MyUsageResponse>(`/api/usage/me?days=${days}`);
