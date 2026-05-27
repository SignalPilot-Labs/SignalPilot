import type { EditorState } from "@codemirror/state";
/**
 * Represents a SQL parsing error with location information
 */
export interface SqlParseError {
    /** Error message describing the issue */
    message: string;
    /** Line number where the error occurred (1-indexed) */
    line: number;
    /** Column number where the error occurred (1-indexed) */
    column: number;
    /** Severity level of the error */
    severity: "error" | "warning";
}
/**
 * Result of parsing a SQL statement
 */
export interface SqlParseResult {
    /** Whether parsing was successful */
    success: boolean;
    /** Array of parsing errors, if any */
    errors: SqlParseError[];
    /** The parsed AST if successful */
    ast?: unknown;
}
export interface SqlParser {
    /**
     * Parse a SQL statement and return the AST
     * @param sql - The SQL statement to parse
     * @param opts - The state of the editor
     * @returns The parsed AST
     */
    parse(sql: string, opts: {
        state: EditorState;
    }): Promise<SqlParseResult>;
    /**
     * Validate a SQL statement and return any errors
     * @param sql - The SQL statement to validate
     * @param opts - The state of the editor
     * @returns An array of errors
     */
    validateSql(sql: string, opts: {
        state: EditorState;
    }): Promise<SqlParseError[]>;
    /**
     * Extract table references from a SQL query
     * @param sql - The SQL query to analyze
     * @param opts - The state of the editor
     * @returns Array of table names referenced in the query
     */
    extractTableReferences(sql: string, opts?: {
        state: EditorState;
    }): Promise<string[]>;
    /**
     * Extract column references from a SQL query
     * @param sql - The SQL query to analyze
     * @param opts - The state of the editor
     * @returns Array of column names referenced in the query
     */
    extractColumnReferences(sql: string, opts?: {
        state: EditorState;
    }): Promise<string[]>;
}
//# sourceMappingURL=types.d.ts.map