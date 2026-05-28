/**
 * Checks if a namespace node is an object with string keys
 */
export function isObjectNamespace(namespace) {
    return typeof namespace === "object" && !Array.isArray(namespace) && !("self" in namespace);
}
/**
 * Checks if a namespace node has self and children properties
 */
export function isSelfChildrenNamespace(namespace) {
    return (typeof namespace === "object" &&
        !Array.isArray(namespace) &&
        "self" in namespace &&
        "children" in namespace);
}
/**
 * Checks if a namespace node is an array of completions/strings
 */
export function isArrayNamespace(namespace) {
    return Array.isArray(namespace);
}
/**
 * Determines the semantic type of an item based on its position and context
 */
function determineSemanticType(path, type, namespace, parentNamespace) {
    // The semantic depth is the number of namespace levels, not the path length
    // For self-children structures, the depth should be based on the logical nesting level
    const depth = path.length;
    // For leaf items (strings or completions in arrays), they are always columns
    if (type === "string" ||
        (type === "completion" && parentNamespace && isArrayNamespace(parentNamespace))) {
        return "column";
    }
    // For namespace items, determine based on structure
    if (type === "namespace" && namespace) {
        if (isArrayNamespace(namespace)) {
            // Arrays represent column collections, so the array itself represents a table
            return "table";
        }
        // For object namespaces, check if they contain tables (arrays)
        if (isObjectNamespace(namespace)) {
            const hasTableChildren = Object.values(namespace).some((child) => isArrayNamespace(child) ||
                (isSelfChildrenNamespace(child) && isArrayNamespace(child.children)));
            if (hasTableChildren) {
                // This namespace contains tables, so it's a schema or database
                return depth <= 1 ? "database" : "schema";
            }
            else {
                // This namespace contains other namespaces
                return depth === 0 ? "database" : "namespace";
            }
        }
    }
    // For completion items with self-children structure
    if (type === "completion" && namespace) {
        if (isArrayNamespace(namespace)) {
            // This completion has column children, so it's a table
            return "table";
        }
        else {
            // This completion has namespace children
            // Check if the children contain tables (arrays) to determine if this is a database or schema
            if (isObjectNamespace(namespace)) {
                const hasTableChildren = Object.values(namespace).some((child) => isArrayNamespace(child) ||
                    (isSelfChildrenNamespace(child) && isArrayNamespace(child.children)));
                if (hasTableChildren) {
                    // Contains tables directly, could be either database or schema depending on depth
                    // For self-children completions, depth 1 means it's actually a root-level database
                    return depth <= 1 ? "database" : "schema";
                }
                else {
                    // Contains other namespaces, so this is a database (unless deeply nested)
                    // For self-children completions, depth 1 means it's actually a root-level database
                    return depth <= 1 ? "database" : "schema";
                }
            }
            else {
                // For other types of children
                // For self-children completions, depth 1 means it's actually a root-level database
                return depth <= 1 ? "database" : "schema";
            }
        }
    }
    // Fallback based on depth
    switch (depth) {
        case 0:
            return "database";
        case 1:
            return "schema";
        default:
            return "namespace";
    }
}
/**
 * Traverses a namespace following a dotted path
 * @param namespace The root namespace to search in
 * @param path The dotted path to traverse (e.g., "db.catalog.table.column")
 * @param config Configuration options
 * @returns The resolved item or null if not found
 */
export function traverseNamespacePath(namespace, path, config = {}) {
    const { maxDepth = 10 } = config;
    // Handle special case of empty path for self-children namespace
    if (path === "" && isSelfChildrenNamespace(namespace)) {
        const semanticType = determineSemanticType([], "completion", namespace.children);
        return {
            completion: namespace.self,
            path: [],
            type: "completion",
            semanticType,
            namespace: namespace.children,
        };
    }
    const pathParts = path.split(".").filter((part) => part.length > 0);
    if (pathParts.length === 0) {
        // Empty path returns null for non-self-children namespaces
        return null;
    }
    if (pathParts.length > maxDepth) {
        return null;
    }
    return traverseNamespaceRecursive(namespace, pathParts, [], config);
}
/**
 * Recursive helper for namespace traversal
 */
function traverseNamespaceRecursive(namespace, remainingPath, currentPath, config, parentNamespace) {
    if (remainingPath.length === 0) {
        // We've reached the end of the path
        if (isSelfChildrenNamespace(namespace)) {
            const semanticType = determineSemanticType(currentPath, "completion", namespace.children, parentNamespace);
            return {
                completion: namespace.self,
                path: currentPath,
                type: "completion",
                semanticType,
                namespace: namespace.children,
            };
        }
        const semanticType = determineSemanticType(currentPath, "namespace", namespace, parentNamespace);
        return {
            path: currentPath,
            type: "namespace",
            semanticType,
            namespace,
        };
    }
    const [currentSegment, ...restPath] = remainingPath;
    const { caseSensitive = false } = config;
    if (!currentSegment) {
        return null;
    }
    if (isObjectNamespace(namespace)) {
        // Search through object keys
        const targetKey = caseSensitive
            ? Object.keys(namespace).find((key) => key === currentSegment)
            : Object.keys(namespace).find((key) => key.toLowerCase() === currentSegment.toLowerCase());
        if (targetKey) {
            const childNamespace = namespace[targetKey];
            if (childNamespace) {
                return traverseNamespaceRecursive(childNamespace, restPath, [...currentPath, targetKey], config, namespace);
            }
        }
    }
    else if (isSelfChildrenNamespace(namespace)) {
        // If this node has self/children, we need to check if the current segment matches the self
        // and then continue with children for the rest of the path
        return traverseNamespaceRecursive(namespace.children, remainingPath, currentPath, config, namespace);
    }
    else if (isArrayNamespace(namespace)) {
        // Check if any item in the array matches
        for (const item of namespace) {
            if (typeof item === "string") {
                const matches = caseSensitive
                    ? item === currentSegment
                    : item.toLowerCase() === currentSegment.toLowerCase();
                if (matches && restPath.length === 0) {
                    const semanticType = determineSemanticType([...currentPath, item], "string", undefined, namespace);
                    return {
                        value: item,
                        path: [...currentPath, item],
                        type: "string",
                        semanticType,
                    };
                }
            }
            else {
                // It's a Completion object
                const matches = caseSensitive
                    ? item.label === currentSegment
                    : item.label.toLowerCase() === currentSegment.toLowerCase();
                if (matches && restPath.length === 0) {
                    const semanticType = determineSemanticType([...currentPath, item.label], "completion", undefined, namespace);
                    return {
                        completion: item,
                        path: [...currentPath, item.label],
                        type: "completion",
                        semanticType,
                    };
                }
            }
        }
    }
    return null;
}
/**
 * Finds all possible completions that match a prefix
 * @param namespace The namespace to search in
 * @param prefix The prefix to match (can be dotted like "db.table")
 * @param config Configuration options
 * @returns Array of resolved items that match the prefix
 */
export function findNamespaceCompletions(namespace, prefix, config = {}) {
    const results = [];
    if (prefix.includes(".")) {
        // Handle dotted prefixes like "db.table"
        const lastDotIndex = prefix.lastIndexOf(".");
        const basePath = prefix.substring(0, lastDotIndex);
        const finalSegment = prefix.substring(lastDotIndex + 1);
        // First traverse to the base path
        const baseNode = traverseNamespacePath(namespace, basePath, config);
        if (baseNode?.namespace) {
            // Then find completions in the target namespace
            return findCompletionsInNamespace(baseNode.namespace, finalSegment, baseNode.path, config);
        }
    }
    else {
        // Simple prefix, search at root level
        return findCompletionsInNamespace(namespace, prefix, [], config);
    }
    return results;
}
/**
 * Finds completions within a specific namespace node
 */
function findCompletionsInNamespace(namespace, prefix, basePath, config) {
    const results = [];
    const { caseSensitive = false, allowPartialMatch = true } = config;
    if (isObjectNamespace(namespace)) {
        for (const [key, value] of Object.entries(namespace)) {
            const matches = allowPartialMatch
                ? caseSensitive
                    ? key.startsWith(prefix)
                    : key.toLowerCase().startsWith(prefix.toLowerCase())
                : caseSensitive
                    ? key === prefix
                    : key.toLowerCase() === prefix.toLowerCase();
            if (matches) {
                if (isSelfChildrenNamespace(value)) {
                    const semanticType = determineSemanticType([...basePath, key], "completion", value.children, namespace);
                    results.push({
                        completion: value.self,
                        path: [...basePath, key],
                        type: "completion",
                        semanticType,
                        namespace: value.children,
                    });
                }
                else {
                    const semanticType = determineSemanticType([...basePath, key], "namespace", value, namespace);
                    results.push({
                        path: [...basePath, key],
                        type: "namespace",
                        semanticType,
                        namespace: value,
                    });
                }
            }
        }
    }
    else if (isSelfChildrenNamespace(namespace)) {
        // If we have a self node, include it if it matches
        const selfMatches = allowPartialMatch
            ? caseSensitive
                ? namespace.self.label.startsWith(prefix)
                : namespace.self.label.toLowerCase().startsWith(prefix.toLowerCase())
            : caseSensitive
                ? namespace.self.label === prefix
                : namespace.self.label.toLowerCase() === prefix.toLowerCase();
        if (selfMatches) {
            const semanticType = determineSemanticType([...basePath, namespace.self.label], "completion", namespace.children);
            results.push({
                completion: namespace.self,
                path: [...basePath, namespace.self.label],
                type: "completion",
                semanticType,
                namespace: namespace.children,
            });
        }
        // Also search in children
        results.push(...findCompletionsInNamespace(namespace.children, prefix, basePath, config));
    }
    else if (isArrayNamespace(namespace)) {
        for (const item of namespace) {
            if (typeof item === "string") {
                const matches = allowPartialMatch
                    ? caseSensitive
                        ? item.startsWith(prefix)
                        : item.toLowerCase().startsWith(prefix.toLowerCase())
                    : caseSensitive
                        ? item === prefix
                        : item.toLowerCase() === prefix.toLowerCase();
                if (matches) {
                    const semanticType = determineSemanticType([...basePath, item], "string", undefined, namespace);
                    results.push({
                        value: item,
                        path: [...basePath, item],
                        type: "string",
                        semanticType,
                    });
                }
            }
            else {
                // It's a Completion object
                const matches = allowPartialMatch
                    ? caseSensitive
                        ? item.label.startsWith(prefix)
                        : item.label.toLowerCase().startsWith(prefix.toLowerCase())
                    : caseSensitive
                        ? item.label === prefix
                        : item.label.toLowerCase() === prefix.toLowerCase();
                if (matches) {
                    const semanticType = determineSemanticType([...basePath, item.label], "completion", undefined, namespace);
                    results.push({
                        completion: item,
                        path: [...basePath, item.label],
                        type: "completion",
                        semanticType,
                    });
                }
            }
        }
    }
    return results;
}
/**
 * Performs a fuzzy search for items by searching for exact segment matches in the full schema path
 * This implements the "crawl back up the tree" functionality with exact segment matching
 * @param namespace The namespace to search in
 * @param identifier The identifier to search for
 * @param config Configuration options
 * @returns Array of possible matches ranked by relevance
 */
export function findNamespaceItemByEndMatch(namespace, identifier, config = {}) {
    const results = [];
    const { maxDepth = 10 } = config;
    // Recursively search through the namespace
    collectAllItems(namespace, [], results, maxDepth);
    // Filter results that have the identifier as an exact segment match anywhere in the path
    const { caseSensitive = false } = config;
    const matchingResults = results.filter((item) => {
        // Check if any segment in the path exactly matches the identifier
        return item.path.some((segment) => caseSensitive ? segment === identifier : segment.toLowerCase() === identifier.toLowerCase());
    });
    // Sort by path length (shorter paths are more specific/relevant)
    // Also prioritize matches where the identifier is at the end of the path
    return matchingResults.sort((a, b) => {
        const aIsLastSegment = caseSensitive
            ? a.path[a.path.length - 1] === identifier
            : a.path[a.path.length - 1]?.toLowerCase() === identifier.toLowerCase();
        const bIsLastSegment = caseSensitive
            ? b.path[b.path.length - 1] === identifier
            : b.path[b.path.length - 1]?.toLowerCase() === identifier.toLowerCase();
        // Prioritize end matches, then by path length
        if (aIsLastSegment && !bIsLastSegment)
            return -1;
        if (!aIsLastSegment && bIsLastSegment)
            return 1;
        return a.path.length - b.path.length;
    });
}
/**
 * Recursively collects all items from a namespace
 */
function collectAllItems(namespace, currentPath, results, maxDepth) {
    if (currentPath.length >= maxDepth) {
        return;
    }
    if (isObjectNamespace(namespace)) {
        for (const [key, value] of Object.entries(namespace)) {
            const newPath = [...currentPath, key];
            if (isSelfChildrenNamespace(value)) {
                const semanticType = determineSemanticType(newPath, "completion", value.children, namespace);
                results.push({
                    completion: value.self,
                    path: newPath,
                    type: "completion",
                    semanticType,
                    namespace: value.children,
                });
                collectAllItems(value.children, newPath, results, maxDepth);
            }
            else {
                const semanticType = determineSemanticType(newPath, "namespace", value, namespace);
                results.push({
                    path: newPath,
                    type: "namespace",
                    semanticType,
                    namespace: value,
                });
                collectAllItems(value, newPath, results, maxDepth);
            }
        }
    }
    else if (isSelfChildrenNamespace(namespace)) {
        const semanticType = determineSemanticType(currentPath, "completion", namespace.children);
        results.push({
            completion: namespace.self,
            path: currentPath,
            type: "completion",
            semanticType,
            namespace: namespace.children,
        });
        collectAllItems(namespace.children, currentPath, results, maxDepth);
    }
    else if (isArrayNamespace(namespace)) {
        for (const item of namespace) {
            if (typeof item === "string") {
                const semanticType = determineSemanticType([...currentPath, item], "string", undefined, namespace);
                results.push({
                    value: item,
                    path: [...currentPath, item],
                    type: "string",
                    semanticType,
                });
            }
            else {
                const semanticType = determineSemanticType([...currentPath, item.label], "completion", undefined, namespace);
                results.push({
                    completion: item,
                    path: [...currentPath, item.label],
                    type: "completion",
                    semanticType,
                });
            }
        }
    }
}
/**
 * Gets the most relevant namespace item using the preference order:
 * 1. Exact match in SQLNamespace
 * 2. Partial/fuzzy match by end identifier
 * @param namespace The namespace to search in
 * @param identifier The identifier to resolve
 * @param config Configuration options
 * @returns The best matching item or null if none found
 */
export function resolveNamespaceItem(namespace, identifier, config = {}) {
    const { enableFuzzySearch = false } = config;
    // First try exact path match
    const exactMatch = traverseNamespacePath(namespace, identifier, config);
    if (exactMatch) {
        return exactMatch;
    }
    // Then try prefix completion (for partial typing)
    const completions = findNamespaceCompletions(namespace, identifier, config);
    if (completions.length > 0) {
        // Return the first completion (should be most relevant)
        return completions[0] || null;
    }
    // Finally try end-match fuzzy search (only if enabled)
    if (enableFuzzySearch) {
        const endMatches = findNamespaceItemByEndMatch(namespace, identifier, config);
        if (endMatches.length > 0) {
            return endMatches[0] || null;
        }
    }
    return null;
}
//# sourceMappingURL=namespace-utils.js.map