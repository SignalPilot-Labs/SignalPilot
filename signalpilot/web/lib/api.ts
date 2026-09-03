// Barrel module for the gateway API client.
// The implementation lives in the lib/api/ modules.
// Import from "~/lib/api" as before. All names re-export from here.

export {
  setClerkTokenGetter,
  setApiKey,
  getAuthHeaders,
  getGatewayAuthToken,
  request,
  ApiRequestError,
  requestErrorStatus,
} from "./api/client";
export * from "./api/eval-upload";
export * from "./api/evals";
export * from "./api/standalone-chat";
export * from "./api/chat-files";
export * from "./api/chat-results";
export * from "./api/chat-reports";
export * from "./api/connections";
export * from "./api/connection-tools";
export * from "./api/projects";
export * from "./api/platform";
export * from "./api/knowledge";
export * from "./api/mcp-connectors";
