import type { Extension } from "@codemirror/state";
import type { SqlParser } from "./types.js";
/**
 * Configuration options for the SQL linter
 */
export interface SqlLinterConfig {
    /** Delay in milliseconds before running validation (default: 750) */
    delay?: number;
    /** Custom SQL parser instance to use for validation */
    parser?: SqlParser;
}
/**
 * Creates a SQL linter extension that validates SQL syntax and reports errors
 *
 * @param config Configuration options for the linter
 * @returns A CodeMirror linter extension
 *
 * @example
 * ```ts
 * import { sqlLinter } from '@/packages/codemirror-sql';
 *
 * const linter = sqlLinter({
 *   delay: 500, // 500ms delay before validation
 *   parser: new SqlParser() // custom parser instance
 * });
 * ```
 */
export declare function sqlLinter(config?: SqlLinterConfig): Extension;
//# sourceMappingURL=diagnostics.d.ts.map