/**
 * Generic resource abstraction that can work with MCP and other backends
 */
export interface Resource<T = unknown> {
    /** Type of the resource */
    type: string;
    /** Unique identifier for the resource */
    uri: string;
    /** Display name for the resource */
    name: string;
    /** Optional description of the resource */
    description?: string;
    /** MIME type of the resource */
    mimeType?: string;
    /** The actual resource data */
    data: T;
}
export interface ResourceProvider<T = unknown> {
    /** Get all available resources */
    getResources(): Promise<Resource<T>[]>;
    /** Get a specific resource by URI */
    getResource?(uri: string): Promise<Resource<T> | null>;
}
/**
 * Generic resource completion options
 */
export interface ResourceCompletionOptions<T = unknown> {
    /** Resource provider to fetch resources from */
    provider: ResourceProvider<T>;
    /** Optional prefix for resource mentions (defaults to '@') */
    prefix?: string;
    /** Optional logger for debugging */
    logger?: typeof console;
    /** Optional callback when a resource is clicked */
    onResourceClick?: (resource: Resource<T>) => void;
    /** Optional callback when hovering over a resource */
    onResourceMouseOver?: (resource: Resource<T>) => void;
    /** Optional callback when hovering out of a resource */
    onResourceMouseOut?: (resource: Resource<T>) => void;
}
/**
 * Convert MCP Resource to generic Resource<T>
 */
export declare function fromMCPResource<T = unknown>(mcpResource: {
    uri: string;
    name: string;
    description?: string;
    mimeType?: string;
}, data: T): Resource<T>;
/**
 * Convert generic Resource<T> to MCP Resource format
 */
export declare function toMCPResource<T>(resource: Resource<T>): {
    uri: string;
    name: string;
    description?: string;
    mimeType?: string;
};
//# sourceMappingURL=resource.d.ts.map