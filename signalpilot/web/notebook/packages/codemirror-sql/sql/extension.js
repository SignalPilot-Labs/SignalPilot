import { sqlLinter } from "./diagnostics.js";
import { defaultSqlHoverTheme, sqlHover } from "./hover.js";
import { sqlStructureGutter } from "./structure-extension.js";
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
export function sqlExtension(config = {}) {
    const extensions = [];
    const { enableLinting = true, enableGutterMarkers = true, enableHover = true, linterConfig, gutterConfig, hoverConfig, } = config;
    if (enableLinting) {
        extensions.push(sqlLinter(linterConfig));
    }
    if (enableGutterMarkers) {
        extensions.push(sqlStructureGutter(gutterConfig));
    }
    if (enableHover) {
        extensions.push(sqlHover(hoverConfig));
        hoverConfig?.theme
            ? extensions.push(hoverConfig.theme)
            : extensions.push(defaultSqlHoverTheme());
    }
    return extensions;
}
//# sourceMappingURL=extension.js.map