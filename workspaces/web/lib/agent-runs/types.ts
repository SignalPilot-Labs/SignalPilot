export const AGENT_RUN_STATUSES = [
  "pending",
  "approval_required",
  "running",
  "succeeded",
  "failed",
  "cancelled",
] as const;

export type AgentRunStatus = (typeof AGENT_RUN_STATUSES)[number];

/**
 * AgentRunV1 — schemaVersion 1.
 *
 * NOTE: future rounds must not reshape; bump schemaVersion for breaking changes.
 *
 * Field-presence invariants by status are enforced by the writer for states it writes
 * (this round: "pending" only). The reader is parse-tolerant of all 6 states so future
 * rounds that mutate the record do not need to bump schemaVersion.
 */
export interface AgentRunV1 {
  schemaVersion: 1;
  /** UUID v4 — generated server-side, never trusted from client */
  id: string;
  /** The full agent prompt, up to 4000 characters */
  prompt: string;
  status: AgentRunStatus;
  /** ISO 8601 UTC */
  createdAt: string;
  /** ISO 8601 UTC — present when status is approval_required, running, succeeded, failed, or cancelled */
  startedAt?: string;
  /** ISO 8601 UTC — present when status is succeeded, failed, or cancelled */
  finishedAt?: string;
  /** Present when status is failed */
  errorMessage?: string;
  /** Present when status is succeeded */
  summary?: string;
  /** Present when status is approval_required — human-readable description of the pending approval */
  pendingApproval?: string;
  /** Optional target workspace ID — deferred to a future round */
  targetWorkspaceId?: string;
}
