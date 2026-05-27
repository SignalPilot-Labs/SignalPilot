import type { Extension } from "@codemirror/state";
import type { Transport } from "@modelcontextprotocol/sdk/shared/transport.js";
import { type Implementation, type Resource as MCPResource, type PromptMessage } from "@modelcontextprotocol/sdk/types.js";
import { type HoverResourceOptions } from "./resources/hover.js";
export interface MCPOptions {
    /** Transport layer for MCP client-server communication */
    transport: Transport;
    /** Optional implementation-specific client options */
    clientOptions?: Implementation;
    /** Optional logger for debugging, defaults to console */
    logger?: typeof console;
    /** Optional callback when a resource is clicked */
    onResourceClick?: (resource: MCPResource) => void;
    /** Optional callback when hovering over a resource */
    onResourceMouseOver?: (resource: MCPResource) => void;
    /** Optional callback when hovering out of a resource */
    onResourceMouseOut?: (resource: MCPResource) => void;
    /** Optional callback when a prompt is triggered */
    onPromptSubmit?: (opts: {
        messages: PromptMessage[];
    }) => void;
    /** Optional hover options */
    hoverOptions?: HoverResourceOptions;
}
export declare function mcpExtension(options: MCPOptions): Extension;
//# sourceMappingURL=mcp.d.ts.map