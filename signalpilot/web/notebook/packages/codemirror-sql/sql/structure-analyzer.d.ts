import type { EditorState } from "@codemirror/state";
import type { SqlParser } from "./types.js";
/**
 * Represents a SQL statement with position information
 */
export interface SqlStatement {
    /** Start position of the statement in the document */
    from: number;
    /** End position of the statement in the document */
    to: number;
    /** First line number of the statement (1-based) */
    lineFrom: number;
    /** Last line number of the statement (1-based) */
    lineTo: number;
    /** The actual SQL content */
    content: string;
    /** Type of SQL statement */
    type: "select" | "insert" | "update" | "delete" | "create" | "drop" | "alter" | "use" | "other";
    /** Whether this statement is syntactically valid */
    isValid: boolean;
}
/**
 * Analyzes SQL documents to extract statement boundaries and information
 * for use with gutter markers and other SQL-aware features.
 */
export declare class SqlStructureAnalyzer {
    private parser;
    private cache;
    private readonly MAX_CACHE_SIZE;
    constructor(parser: SqlParser);
    /**
     * Analyzes the document and extracts all SQL statements
     */
    analyzeDocument(state: EditorState): Promise<SqlStatement[]>;
    /**
     * Gets the SQL statement at a specific cursor position
     */
    getStatementAtPosition(state: EditorState, position: number): Promise<SqlStatement | null>;
    /**
     * Gets all SQL statements that intersect with a selection range
     */
    getStatementsInRange(state: EditorState, from: number, to: number): Promise<SqlStatement[]>;
    private extractStatements;
    private splitByStatementSeparators;
    private determineStatementType;
    private stripComments;
    private generateCacheKey;
    /**
     * Clears the internal cache
     */
    clearCache(): void;
}
//# sourceMappingURL=structure-analyzer.d.ts.map