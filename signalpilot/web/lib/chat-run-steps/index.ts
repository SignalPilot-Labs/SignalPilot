/**
 * Folds the raw standalone-chat run event stream into renderable steps,
 * blocks, plans and boot state for the agent activity timeline. Everything
 * here is pure and synchronous so it can be unit tested and replayed
 * deterministically on the fixture page.
 */

export type {
  DashboardAuthoringProgress,
  PlanItem,
  PlanItemStatus,
  RunBlock,
  RunPlan,
  RunStep,
  RunStepCategory,
  RunStepStatus,
  RunStepSummary,
  RuntimeBootPhase,
  RuntimeBootState,
} from "./types";
export {
  asRecord,
  chatToolSummary,
  CONNECTOR_NEEDS_SIGN_IN,
  durationBetween,
  text,
} from "./payload";
export {
  categorizeTool,
  extractCode,
  extractFile,
  extractSources,
  humanizeTool,
  normalizeToolName,
  SUBAGENT_SPAWN_TOOLS,
} from "./tool-names";
export { foldRunSteps } from "./fold-steps";
export { foldRunBlocks, shouldShowAgentThinking } from "./fold-blocks";
export type * from "./tool-result-types";
export { parseToolResult, toolResultKindForTool } from "./tool-results";
export {
  deriveLiveState,
  deriveLiveStateFromBlocks,
  type RunLiveInfo,
  type RunLiveState,
} from "./live-state";
export {
  activeDashboardAuthoringProgress,
  activeDashboardPreviewLabel,
  describeSubagentWork,
  extractRunPlan,
  extractRuntimeBoot,
  formatErrorSupportBundle,
  formatStepDuration,
  shouldShowRuntimeBoot,
  summarizeRunSteps,
} from "./run-extras";
export { formatCount, formatMs, toCsv } from "./format";
