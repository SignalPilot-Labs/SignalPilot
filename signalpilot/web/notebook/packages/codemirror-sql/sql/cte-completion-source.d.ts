import type { CompletionSource } from "@codemirror/autocomplete";
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
export declare const cteCompletionSource: CompletionSource;
//# sourceMappingURL=cte-completion-source.d.ts.map