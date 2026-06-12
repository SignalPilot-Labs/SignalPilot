import { debug } from "../debug.js";
import { lazy } from "../utils.js";
/**
 * A SQL parser wrapper around node-sql-parser with enhanced error handling
 * and validation capabilities for CodeMirror integration.
 *
 * @example Custom dialect
 * ```ts
 * import { NodeSqlParser } from "@/packages/codemirror-sql";
 *
 * const myParser = new NodeSqlParser({
 *   getParserOptions: (state) => ({
 *     dialect: getDialect(state),
 *     parseOptions: {
 *       includeLocations: true,
 *     },
 *   }),
 * });
 * ```
 */
export class NodeSqlParser {
    opts;
    parser = null;
    // Record the column number to the offset amount
    offsetRecord = {};
    constructor(opts = {}) {
        this.opts = opts;
    }
    /**
     * Lazy import of the node-sql-parser package and create a new Parser instance.
     */
    getParser = lazy(async () => {
        if (this.parser) {
            return this.parser;
        }
        const module = await import("node-sql-parser");
        // Support for ESM and CJS
        const { Parser } = module.default || module;
        this.parser = new Parser();
        return this.parser;
    });
    async parse(sql, opts) {
        // Reset the offset map on each parse
        this.offsetRecord = {};
        const parserOptions = this.opts.getParserOptions?.(opts.state);
        const sanitizedSql = await this.sanitizeSql(sql, parserOptions);
        try {
            const parser = await this.getParser();
            // Check if this is DuckDB dialect and apply custom processing
            if (parserOptions?.database === "DuckDB") {
                return this.parseWithDuckDBSupport(sanitizedSql, parserOptions);
            }
            const ast = parser.astify(sanitizedSql, parserOptions);
            return {
                success: true,
                errors: [],
                ast,
            };
        }
        catch (error) {
            const parseError = this.extractErrorInfo(error, sanitizedSql);
            return {
                success: false,
                errors: [parseError],
            };
        }
    }
    async sanitizeSql(sql, parserOptions) {
        if (parserOptions?.ignoreBrackets) {
            const { sql: replacedSql, offsetRecord } = replaceBracketsWithQuotes(sql);
            this.offsetRecord = offsetRecord;
            return replacedSql;
        }
        return sql;
    }
    /**
     * Parse SQL with DuckDB syntax support
     * This is not robust, we catch main cases.
     */
    async parseWithDuckDBSupport(sql, parserOptions) {
        const parser = await this.getParser();
        // Remove comments and normalize for pattern checking
        const sqlToCheck = removeCommentsFromStart(sql).trimStart().toLowerCase();
        // Handle unsupported DuckDB syntax patterns
        if (sqlToCheck.startsWith("from") || sqlToCheck.includes("macro")) {
            debug("Unsupported DuckDB syntax");
            return { success: true, errors: [] };
        }
        let modifiedSql = sql;
        // Postgres does not support `CREATE OR REPLACE` for tables
        if (sqlToCheck.includes("create or replace table")) {
            const offset = "create or replace table".length - "create table".length;
            this.offsetRecord[sql.indexOf("create or replace table")] = -offset;
            modifiedSql = sql.replace(/create or replace table/i, "create table");
        }
        // Try standard parsing with PostgreSQL dialect
        try {
            const postgresOptions = { ...parserOptions, database: "PostgreSQL" };
            const ast = parser.astify(modifiedSql, postgresOptions);
            return { success: true, errors: [], ast };
        }
        catch (error) {
            // Use the original sql since we manually apply the offset
            const parseError = this.extractErrorInfo(error, sql);
            return { success: false, errors: [parseError] };
        }
    }
    /**
     * @param error - The error object
     * @param sql - The SQL string
     * @param offset - The offset to add to the column position. Default is 0.
     * @returns The parsed error information
     */
    extractErrorInfo(error, sql) {
        let line = 1;
        let column = 1;
        const message = error?.message || "SQL parsing error";
        const errorObj = error;
        if (errorObj?.location) {
            line = errorObj.location.start?.line || 1;
            column = errorObj.location.start?.column || 1;
        }
        else if (errorObj?.hash) {
            line = errorObj.hash.line || 1;
            column = errorObj.hash.loc?.first_column || 1;
        }
        else {
            const lineMatch = message.match(/line (\d+)/i);
            const columnMatch = message.match(/column (\d+)/i);
            if (lineMatch?.[1]) {
                line = parseInt(lineMatch[1], 10);
            }
            if (columnMatch?.[1]) {
                column = parseInt(columnMatch[1], 10);
            }
        }
        /**
         * Add offset to the column position to get the correct position of the error
         * SELECT {id} FRO users
         *             ^ error position should be here
         *
         * SELECT {id} FRO users
         *                   ^ user sees this
         * So in this case, we subtract the offset from the column position.
         *
         * If the error is before the brackets, we don't need to add the offset because it just increases the string length
         * Column position will be the same as the user sees.
         */
        for (const [position, offset] of Object.entries(this.offsetRecord)) {
            if (column > parseInt(position, 10)) {
                column -= offset;
            }
        }
        // Ensure we don't exceed the sql length
        if (column > sql.length) {
            column = sql.length;
        }
        return {
            message: this.cleanErrorMessage(message),
            line: Math.max(1, line),
            column: column,
            severity: "error",
        };
    }
    cleanErrorMessage(message) {
        return message
            .replace(/^Error: /, "")
            .replace(/Expected .* but .* found\./i, (match) => match.replace(/but .* found/, "found unexpected token"))
            .trim();
    }
    async validateSql(sql, opts) {
        const result = await this.parse(sql, opts);
        return result.errors;
    }
    /**
     * Extracts table references from a SQL query using node-sql-parser
     * @param sql The SQL query to analyze
     * @returns Array of table names referenced in the query
     */
    async extractTableReferences(sql, opts) {
        const parserOptions = opts ? this.opts.getParserOptions?.(opts.state) : undefined;
        try {
            const parser = await this.getParser();
            const tableList = parser.tableList(sql, parserOptions);
            // Clean up table names - node-sql-parser returns format like "select::null::users"
            return tableList.map((table) => {
                const parts = table.split("::");
                return parts[parts.length - 1] || table;
            });
        }
        catch {
            return [];
        }
    }
    /**
     * Extracts column references from a SQL query using node-sql-parser
     * @param sql The SQL query to analyze
     * @returns Array of column names referenced in the query
     */
    async extractColumnReferences(sql, opts) {
        const parserOptions = opts?.state ? this.opts.getParserOptions?.(opts.state) : undefined;
        try {
            const parser = await this.getParser();
            const columnList = parser.columnList(sql, parserOptions);
            // Clean up column names - node-sql-parser returns format like "select::null::users"
            const cleanColumnList = columnList.map((column) => {
                const parts = column.split("::");
                return parts[parts.length - 1] || column;
            });
            return cleanColumnList;
        }
        catch {
            return [];
        }
    }
}
function removeCommentsFromStart(sql, commentTypes = ["/*", "--"]) {
    const regexPatterns = [];
    // Multi-line comments
    if (commentTypes.includes("/*")) {
        regexPatterns.push("/\\*[\\s\\S]*?\\*/");
    }
    // Single-line comments
    if (commentTypes.includes("--")) {
        regexPatterns.push("--[^\\n]*");
    }
    if (regexPatterns.length === 0)
        return sql;
    const commentRegex = new RegExp(`^\\s*(${regexPatterns.join("|")})\\s*`, "");
    // Keep removing comments from the start until no more are found
    let result = sql;
    let prevResult = "";
    while (result !== prevResult) {
        prevResult = result;
        result = result.replace(commentRegex, "");
    }
    return result;
}
const QUOTE_LENGTH = "''".length;
/**
 * Replaces unquoted curly bracket expressions (e.g., {id}) with quoted strings (e.g., '{id}'),
 * ignoring brackets already inside single or double quotes.
 *
 * Returns the modified SQL and a record mapping the index of each replaced bracket to the
 * number of characters added (for offset tracking).
 *
 * @example
 *   replaceBracketsWithQuotes("SELECT {id}, '{name}' FROM users");
 *   // => {
 *   //   sql: "SELECT '{id}', '{name}' FROM users",
 *   //   offsetRecord: { 7: 2 }
 *   // }
 */
function replaceBracketsWithQuotes(sql) {
    const offsetRecord = {};
    const replacedSql = sql.replace(/("(?:[^"\\]|\\.)*")|('(?:[^'\\]|\\.)*')|(\{[^}]*\})/g, (match, doubleQuoted, singleQuoted, bracket, offset) => {
        // If it's a quoted string, return it as-is
        if (doubleQuoted || singleQuoted) {
            return match;
        }
        // If it's a bracket, quote it and record the offset
        if (bracket) {
            offsetRecord[offset] = QUOTE_LENGTH;
            return `'${bracket}'`;
        }
        return match;
    });
    return { sql: replacedSql, offsetRecord };
}
export const exportedForTesting = { replaceBracketsWithQuotes, removeCommentsFromStart };
//# sourceMappingURL=parser.js.map