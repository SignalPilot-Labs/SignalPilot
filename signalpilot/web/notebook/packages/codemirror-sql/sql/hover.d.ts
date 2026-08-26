import type { SQLDialect, SQLNamespace } from "@codemirror/lang-sql";
import type { Extension } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { type ResolvedNamespaceItem } from "./namespace-utils.js";
import type { SqlParser } from "./types.js";
/**
 * Creates a filtered namespace that only includes tables referenced in the query
 * @param schema The full schema namespace
 * @param tableRefs Set of table names referenced in the query
 * @returns Filtered namespace containing only referenced tables
 */
export declare function filterSchemaByTableRefs(schema: SQLNamespace, tableRefs: Set<string>): SQLNamespace;
/**
 * SQL schema information for hover tooltips
 */
export interface SqlSchema {
    [tableName: string]: string[];
}
/**
 * SQL keyword information
 */
export interface SqlKeywordInfo {
    description?: string;
    syntax?: string;
    example?: string;
    metadata?: Record<string, string>;
}
/**
 * Data passed to keyword tooltip renderers
 */
export interface KeywordTooltipData {
    keyword: string;
    info: SqlKeywordInfo;
}
/**
 * Data passed to namespace tooltip renderers (namespace, table, column)
 */
export interface NamespaceTooltipData {
    item: ResolvedNamespaceItem;
    /** The word being hovered over */
    word: string;
    /** The resolved schema context */
    resolvedSchema: SQLNamespace;
}
/**
 * Configuration for SQL hover tooltips
 */
export interface SqlHoverConfig {
    /** Database schema for table and column information */
    schema?: SQLNamespace | ((view: EditorView) => SQLNamespace);
    /** SQL dialect for keyword information */
    dialect?: SQLDialect | ((view: EditorView) => SQLDialect);
    /** Custom keyword information */
    keywords?: Record<string, SqlKeywordInfo> | ((view: EditorView) => Promise<Record<string, SqlKeywordInfo>>);
    /** Hover delay in milliseconds (default: 300) */
    hoverTime?: number;
    /** Enable hover for keywords (default: true) */
    enableKeywords?: boolean;
    /** Enable hover for tables (default: true) */
    enableTables?: boolean;
    /** Enable hover for columns (default: true) */
    enableColumns?: boolean;
    /** Enable fuzzy search for namespace items (default: false) */
    enableFuzzySearch?: boolean;
    /** Custom SQL parser instance to use for query analysis */
    parser?: SqlParser;
    /** Custom tooltip render function - highest priority, returns HTMLElement or null for fallback */
    tooltipRender?: (word: string, view: EditorView, pos: number) => HTMLElement | null;
    /** Custom tooltip renderers for different item types */
    tooltipRenderers?: {
        /** Custom renderer for SQL keywords */
        keyword?: (data: KeywordTooltipData) => string;
        /** Custom renderer for namespace items (database, schema, generic namespace) */
        namespace?: (data: NamespaceTooltipData) => string;
        /** Custom renderer for table items */
        table?: (data: NamespaceTooltipData) => string;
        /** Custom renderer for column items */
        column?: (data: NamespaceTooltipData) => string;
    };
    /** Custom CSS theme for hover tooltips */
    theme?: Extension;
}
/**
 * Creates a hover tooltip extension for SQL
 */
export declare function sqlHover(config?: SqlHoverConfig): Extension;
/**
 * Creates HTML content for namespace-resolved items
 */
declare function createNamespaceTooltip(item: ResolvedNamespaceItem): string;
/**
 * Creates HTML content for keyword tooltips
 * Renders metadata as tags if present
 */
declare function createKeywordTooltip(opts: {
    keyword: string;
    info: SqlKeywordInfo;
}): string;
/**
 * Creates HTML content for table tooltips
 */
declare function createTableTooltip(opts: {
    tableName: string;
    columns: string[];
    metadata?: Record<string, string>;
}): string;
/**
 * Creates HTML content for column tooltips
 */
declare function createColumnTooltip(opts: {
    tableName: string;
    columnName: string;
    schema: SqlSchema;
    metadata?: Record<string, string>;
}): string;
export declare const DefaultSqlTooltipRenders: {
    keyword: typeof createKeywordTooltip;
    table: typeof createTableTooltip;
    column: typeof createColumnTooltip;
    namespace: typeof createNamespaceTooltip;
};
/**
 * Default CSS styles for hover tooltips
 */
export declare const defaultSqlHoverTheme: (theme?: "light" | "dark") => Extension;
export {};
//# sourceMappingURL=hover.d.ts.map