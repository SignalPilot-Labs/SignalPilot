import { linter } from "@codemirror/lint";
import { NodeSqlParser } from "./parser.js";
const DEFAULT_DELAY = 750;
/**
 * Converts a SQL parse error to a CodeMirror diagnostic
 */
function convertToCodeMirrorDiagnostic(error, doc) {
    const lineStart = doc.line(error.line).from;
    const from = lineStart + Math.max(0, error.column - 1);
    const to = from + 1;
    return {
        from,
        to,
        severity: error.severity,
        message: error.message,
        source: "sql-parser",
    };
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
export function sqlLinter(config = {}) {
    const parser = config.parser || new NodeSqlParser();
    return linter(async (view) => {
        const doc = view.state.doc;
        const sql = doc.toString();
        if (!sql.trim()) {
            return [];
        }
        const errors = await parser.validateSql(sql, { state: view.state });
        return errors.map((error) => convertToCodeMirrorDiagnostic(error, doc));
    }, {
        delay: config.delay || DEFAULT_DELAY,
    });
}
//# sourceMappingURL=diagnostics.js.map