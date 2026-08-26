import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import type { Transport } from "@modelcontextprotocol/sdk/shared/transport.js";
import { type Implementation } from "@modelcontextprotocol/sdk/types.js";
import { type Resource, type ResourceProvider } from "../resources/resource.js";
/**
 * MCP-specific resource provider that implements the generic ResourceProvider interface
 */
export declare class MCPResourceProvider implements ResourceProvider<string> {
    private logger?;
    private client;
    private connectedPromise;
    constructor(transport: Transport, clientOptions?: Implementation, logger?: typeof console | undefined);
    getResources(): Promise<Resource<string>[]>;
    getResource(uri: string): Promise<Resource<string> | null>;
    /**
     * Get the underlying MCP client for advanced usage
     */
    getClient(): Client;
    /**
     * Check if the client is connected
     */
    isConnected(): Promise<boolean>;
}
//# sourceMappingURL=mcp-provider.d.ts.map