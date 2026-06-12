import type { Extension } from "@codemirror/state";
import { type SqlLinterConfig } from "./diagnostics.js";
import { type SqlHoverConfig } from "./hover.js";
import { type SqlGutterConfig } from "./structure-extension.js";
/**
 * Configuration options for the SQL extension
 */
export interface SqlExtensionConfig {
    /** Whether to enable SQL linting (default: true) */
    enableLinting?: boolean;
    /** Configuration for the SQL linter */
    linterConfig?: SqlLinterConfig;
    /** Whether to enable gutter markers for SQL statements (default: true) */
    enableGutterMarkers?: boolean;
    /** Configuration for the SQL gutter markers */
    gutterConfig?: SqlGutterConfig;
    /** Whether to enable hover tooltips (default: true) */
    enableHover?: boolean;
    /** Configuration for hover tooltips */
    hoverConfig?: SqlHoverConfig;
}
/**
 * Creates a comprehensive SQL extension for CodeMirror that includes:
 * - SQL syntax validation and linting
 * - Visual gutter indicators for SQL statements
 * - Hover tooltips for keywords, tables, and columns
 *
 * @param config Configuration options for the extension
 * @returns An array of CodeMirror extensions
 *
 * @example
 * ```ts
 * import { sqlExtension } from '@/packages/codemirror-sql';
 *
 * const editor = new EditorView({
 *   extensions: [
 *     sqlExtension({
 *       linterConfig: { delay: 500 },
 *       gutterConfig: { backgroundColor: '#3b82f6' },
 *       hoverConfig: { hoverTime: 300 }
 *     })
 *   ]
 * });
 * ```
 */
export declare function sqlExtension(config?: SqlExtensionConfig): Extension[];
//# sourceMappingURL=extension.d.ts.map