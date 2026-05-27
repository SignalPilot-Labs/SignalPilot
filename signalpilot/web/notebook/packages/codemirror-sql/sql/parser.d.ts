import type { EditorState } from "@codemirror/state";
import type { AST, Option } from "node-sql-parser";
import type { SqlParseError, SqlParseResult, SqlParser } from "./types.js";
export interface ParserOption extends Option {
    database: SupportedDialects;
    /**
     * If true, the parser will quote brackets in the SQL query which will satisfy the parser.
     * This is useful if you want to interpolate variables in f-strings.
     *
     * @example
     * ```sql
     * SELECT {id} -> SELECT '{id}'
     * ```
     *
     * @experimental This is an experimental feature and may break parsing.
     */
    ignoreBrackets?: boolean;
}
export interface NodeSqlParserOptions {
    getParserOptions?: (state: EditorState) => ParserOption;
}
export interface NodeSqlParserResult extends SqlParseResult {
    ast?: AST | AST[];
}
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
export declare class NodeSqlParser implements SqlParser {
    private opts;
    private parser;
    private offsetRecord;
    constructor(opts?: NodeSqlParserOptions);
    /**
     * Lazy import of the node-sql-parser package and create a new Parser instance.
     */
    private getParser;
    parse(sql: string, opts: {
        state: EditorState;
    }): Promise<NodeSqlParserResult>;
    sanitizeSql(sql: string, parserOptions?: ParserOption): Promise<string>;
    /**
     * Parse SQL with DuckDB syntax support
     * This is not robust, we catch main cases.
     */
    private parseWithDuckDBSupport;
    /**
     * @param error - The error object
     * @param sql - The SQL string
     * @param offset - The offset to add to the column position. Default is 0.
     * @returns The parsed error information
     */
    private extractErrorInfo;
    private cleanErrorMessage;
    validateSql(sql: string, opts: {
        state: EditorState;
    }): Promise<SqlParseError[]>;
    /**
     * Extracts table references from a SQL query using node-sql-parser
     * @param sql The SQL query to analyze
     * @returns Array of table names referenced in the query
     */
    extractTableReferences(sql: string, opts?: {
        state: EditorState;
    }): Promise<string[]>;
    /**
     * Extracts column references from a SQL query using node-sql-parser
     * @param sql The SQL query to analyze
     * @returns Array of column names referenced in the query
     */
    extractColumnReferences(sql: string, opts?: {
        state: EditorState;
    }): Promise<string[]>;
}
type CommentType = "--" | "/*";
declare function removeCommentsFromStart(sql: string, commentTypes?: CommentType[]): string;
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
declare function replaceBracketsWithQuotes(sql: string): {
    sql: string;
    offsetRecord: Record<number, number>;
};
export declare const exportedForTesting: {
    replaceBracketsWithQuotes: typeof replaceBracketsWithQuotes;
    removeCommentsFromStart: typeof removeCommentsFromStart;
};
/**
 * https://github.com/taozhi8833998/node-sql-parser?tab=readme-ov-file#supported-database-sql-syntax
 * While DuckDB is not supported in the library, we perform some special handling for it and treat it as PostgreSQL.
 */
export type SupportedDialects = "Athena" | "BigQuery" | "DB2" | "Hive" | "MariaDB" | "MySQL" | "PostgreSQL" | "DuckDB" | "Redshift" | "Sqlite" | "TransactSQL" | "FlinkSQL" | "Snowflake" | "Noql";
export {};
//# sourceMappingURL=parser.d.ts.map