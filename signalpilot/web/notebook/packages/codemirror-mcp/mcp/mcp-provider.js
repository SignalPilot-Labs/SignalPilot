import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { ListResourcesResultSchema, ReadResourceResultSchema, } from "@modelcontextprotocol/sdk/types.js";
import { fromMCPResource } from "../resources/resource.js";
/**
 * MCP-specific resource provider that implements the generic ResourceProvider interface
 */
export class MCPResourceProvider {
    logger;
    client;
    connectedPromise;
    constructor(transport, clientOptions, logger) {
        this.logger = logger;
        this.client = new Client({
            name: clientOptions?.name ?? "codemirror-mcp",
            version: clientOptions?.version ?? "0.1.0",
        }, {
            capabilities: {},
        });
        this.connectedPromise = this.client
            .connect(transport)
            .then(() => {
            this.logger?.log("Connected to MCP server");
            return true;
        })
            .catch((error) => {
            this.logger?.error("Failed to connect to MCP server:", error);
            return false;
        });
    }
    async getResources() {
        const connected = await this.connectedPromise;
        if (!connected) {
            throw new Error("MCP client is not connected");
        }
        try {
            const response = await this.client.request({ method: "resources/list" }, ListResourcesResultSchema);
            const resources = [];
            // Guard against malformed response data
            if (!response.resources || !Array.isArray(response.resources)) {
                this.logger?.warn("Malformed response: resources is not an array");
                return [];
            }
            // For each resource, we could potentially read its content
            // For now, we'll just return the resource metadata with empty data
            for (const mcpResource of response.resources) {
                resources.push(fromMCPResource(mcpResource, ""));
            }
            return resources;
        }
        catch (error) {
            this.logger?.error("Failed to fetch MCP resources:", error);
            throw error;
        }
    }
    async getResource(uri) {
        const connected = await this.connectedPromise;
        if (!connected) {
            throw new Error("MCP client is not connected");
        }
        try {
            // First get the resource metadata
            const listResponse = await this.client.request({ method: "resources/list" }, ListResourcesResultSchema);
            // Guard against malformed response data
            if (!listResponse.resources || !Array.isArray(listResponse.resources)) {
                this.logger?.warn("Malformed response: resources is not an array");
                return null;
            }
            const mcpResource = listResponse.resources.find((r) => r.uri === uri);
            if (!mcpResource) {
                return null;
            }
            // Try to read the resource content
            let content = "";
            try {
                const readResponse = await this.client.request({ method: "resources/read", params: { uri } }, ReadResourceResultSchema);
                // Combine all content parts
                content = readResponse.contents.map((c) => c.text || c.blob || "").join("\n");
            }
            catch (error) {
                this.logger?.warn(`Could not read resource ${uri}:`, error);
                // Continue with empty content
            }
            return fromMCPResource(mcpResource, content);
        }
        catch (error) {
            this.logger?.error("Failed to get MCP resource:", error);
            throw error;
        }
    }
    /**
     * Get the underlying MCP client for advanced usage
     */
    getClient() {
        return this.client;
    }
    /**
     * Check if the client is connected
     */
    async isConnected() {
        return this.connectedPromise;
    }
}
//# sourceMappingURL=mcp-provider.js.map