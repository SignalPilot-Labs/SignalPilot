/**
 * Generic resource abstraction that can work with MCP and other backends
 */
/**
 * Convert MCP Resource to generic Resource<T>
 */
export function fromMCPResource(mcpResource, data) {
    const protocolMatch = mcpResource.uri.split("://");
    let type;
    if (protocolMatch.length > 1) {
        // Has protocol separator - use the first part as type
        type = protocolMatch[0] ?? "unknown";
    }
    else {
        // No protocol separator - mark as unknown
        type = "unknown";
    }
    return {
        type,
        uri: mcpResource.uri,
        name: mcpResource.name,
        description: mcpResource.description,
        mimeType: mcpResource.mimeType,
        data,
    };
}
/**
 * Convert generic Resource<T> to MCP Resource format
 */
export function toMCPResource(resource) {
    return {
        uri: resource.uri,
        name: resource.name,
        description: resource.description,
        mimeType: resource.mimeType,
    };
}
//# sourceMappingURL=resource.js.map