/**
 * A completion source for Common Table Expressions (CTEs) in SQL
 *
 * This function provides autocomplete suggestions for CTE references based on
 * WITH clauses found in the current SQL document.
 *
 * @param context The completion context from CodeMirror
 * @returns Completion result with CTE suggestions or null if no completions available
 *
 * @example
 * ```ts
 * import { cteCompletionSource } from '@/packages/codemirror-sql';
 * import { StandardSQL } from '@codemirror/lang-sql';
 *
 * // Add to SQL language configuration
 * StandardSQL.language.data.of({
 *   autocomplete: cteCompletionSource,
 * })
 * ```
 */
export const cteCompletionSource = (context) => {
    const doc = context.state.doc.toString();
    const cteNames = new Set();
    // Find all CTEs in the document using regex pattern
    // Match WITH clause and extract CTE names
    const ctePattern = /WITH\s+(?:RECURSIVE\s+)?([a-zA-Z_][a-zA-Z0-9_]*)\s+AS\s*\(/gi;
    let match;
    match = ctePattern.exec(doc);
    while (match !== null) {
        const cteName = match[1];
        if (cteName) {
            cteNames.add(cteName);
        }
        match = ctePattern.exec(doc);
    }
    // Also match additional CTEs in the same WITH clause (comma-separated)
    const additionalCtePattern = /WITH\s+(?:RECURSIVE\s+)?[a-zA-Z_][a-zA-Z0-9_]*\s+AS\s*\([^)]*\)(?:\s*,\s*([a-zA-Z_][a-zA-Z0-9_]*)\s+AS\s*\([^)]*\))*/gi;
    match = additionalCtePattern.exec(doc);
    while (match !== null) {
        // Extract all comma-separated CTEs
        const fullMatch = match[0];
        const cteChainPattern = /([a-zA-Z_][a-zA-Z0-9_]*)\s+AS\s*\(/g;
        let cteMatch = cteChainPattern.exec(fullMatch);
        while (cteMatch !== null) {
            const cteName = cteMatch[1];
            if (cteName) {
                cteNames.add(cteName);
            }
            cteMatch = cteChainPattern.exec(fullMatch);
        }
        match = additionalCtePattern.exec(doc);
    }
    // If no CTEs found, return null (no completions)
    if (cteNames.size === 0) {
        return null;
    }
    // Get the word being typed
    const word = context.matchBefore(/\w*/);
    if (!word) {
        return null;
    }
    // If no word is being typed and not in explicit mode, don't show completions
    if (word.from === word.to && !context.explicit) {
        return null;
    }
    // Create completion objects for each CTE
    const completions = Array.from(cteNames).map((cteName) => ({
        label: cteName,
        type: "variable", // CTEs are like temporary tables/variables
        info: `Common Table Expression: ${cteName}`,
        boost: 10, // Give CTEs higher priority than regular completions
    }));
    return {
        from: word.from,
        options: completions,
    };
};
//# sourceMappingURL=cte-completion-source.js.map