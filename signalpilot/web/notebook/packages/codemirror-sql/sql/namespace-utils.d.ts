import type { Completion } from "@codemirror/autocomplete";
import type { SQLNamespace } from "@codemirror/lang-sql";
/**
 * Semantic type for SQL namespace items
 */
export type SemanticType = "database" | "schema" | "table" | "column" | "namespace";
/**
 * Represents a resolved namespace item with its path and metadata
 */
export interface ResolvedNamespaceItem {
    /** The completion object if this is a terminal node */
    completion?: Completion;
    /** The string value if this is a string terminal */
    value?: string;
    /** The full path to this item */
    path: string[];
    /** The basic type of this item */
    type: "completion" | "string" | "namespace";
    /** The semantic SQL type of this item */
    semanticType: SemanticType;
    /** The original namespace node */
    namespace?: SQLNamespace;
}
/**
 * Configuration for namespace search operations
 */
export interface NamespaceSearchConfig {
    /** Maximum depth to search (default: 10) */
    maxDepth?: number;
    /** Whether to perform case-sensitive matching (default: false) */
    caseSensitive?: boolean;
    /** Whether to allow partial matching (default: true) */
    allowPartialMatch?: boolean;
    /** Whether to enable fuzzy search (default: false) */
    enableFuzzySearch?: boolean;
}
/**
 * Checks if a namespace node is an object with string keys
 */
export declare function isObjectNamespace(namespace: SQLNamespace): namespace is {
    [name: string]: SQLNamespace;
};
/**
 * Checks if a namespace node has self and children properties
 */
export declare function isSelfChildrenNamespace(namespace: SQLNamespace): namespace is {
    self: Completion;
    children: SQLNamespace;
};
/**
 * Checks if a namespace node is an array of completions/strings
 */
export declare function isArrayNamespace(namespace: SQLNamespace): namespace is readonly (Completion | string)[];
/**
 * Traverses a namespace following a dotted path
 * @param namespace The root namespace to search in
 * @param path The dotted path to traverse (e.g., "db.catalog.table.column")
 * @param config Configuration options
 * @returns The resolved item or null if not found
 */
export declare function traverseNamespacePath(namespace: SQLNamespace, path: string, config?: NamespaceSearchConfig): ResolvedNamespaceItem | null;
/**
 * Finds all possible completions that match a prefix
 * @param namespace The namespace to search in
 * @param prefix The prefix to match (can be dotted like "db.table")
 * @param config Configuration options
 * @returns Array of resolved items that match the prefix
 */
export declare function findNamespaceCompletions(namespace: SQLNamespace, prefix: string, config?: NamespaceSearchConfig): ResolvedNamespaceItem[];
/**
 * Performs a fuzzy search for items by searching for exact segment matches in the full schema path
 * This implements the "crawl back up the tree" functionality with exact segment matching
 * @param namespace The namespace to search in
 * @param identifier The identifier to search for
 * @param config Configuration options
 * @returns Array of possible matches ranked by relevance
 */
export declare function findNamespaceItemByEndMatch(namespace: SQLNamespace, identifier: string, config?: NamespaceSearchConfig): ResolvedNamespaceItem[];
/**
 * Gets the most relevant namespace item using the preference order:
 * 1. Exact match in SQLNamespace
 * 2. Partial/fuzzy match by end identifier
 * @param namespace The namespace to search in
 * @param identifier The identifier to resolve
 * @param config Configuration options
 * @returns The best matching item or null if none found
 */
export declare function resolveNamespaceItem(namespace: SQLNamespace, identifier: string, config?: NamespaceSearchConfig): ResolvedNamespaceItem | null;
//# sourceMappingURL=namespace-utils.d.ts.map