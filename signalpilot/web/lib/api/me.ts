// GET /api/me — who the caller is inside the org, and what they may do.
// Scope `read`, no plan gate; cheap enough for every page.

import { request } from "./client";
import type { DeploymentCapabilities, EntitlementPayload } from "~/lib/entitlement";

export type MePayload = {
  user_id: string | null;
  org_id: string | null;
  role: "admin" | "member";
  is_admin: boolean;
  permissions: string[];
  entitlement?: EntitlementPayload | null;
  capabilities?: DeploymentCapabilities | null;
};

export const getMe = () => request<MePayload>("/api/me");
