import type { AgentRunStatus } from "@/lib/agent-runs/types";

export const STATUS_LABEL: Record<AgentRunStatus, string> = {
  pending: "Pending",
  approval_required: "Approval required",
  running: "Running",
  succeeded: "Succeeded",
  failed: "Failed",
  cancelled: "Cancelled",
};
