import { EditorView, hoverTooltip } from "@codemirror/view";
import { debug } from "../debug.js";
import { isArrayNamespace, isObjectNamespace, resolveNamespaceItem, } from "./namespace-utils.js";
import { NodeSqlParser } from "./parser.js";
/**
 * Creates a filtered namespace that only includes tables referenced in the query
 * @param schema The full schema namespace
 * @param tableRefs Set of table names referenced in the query
 * @returns Filtered namespace containing only referenced tables
 */
export function filterSchemaByTableRefs(schema, tableRefs) {
    if (tableRefs.size === 0) {
        // If no tables are referenced, return empty schema to avoid showing irrelevant columns
        return {};
    }
    if (isObjectNamespace(schema)) {
        const filtered = {};
        for (const [key, value] of Object.entries(schema)) {
            // Check if this table is referenced (case-insensitive)
            const isReferenced = Array.from(tableRefs).some((refTable) => refTable.toLowerCase() === key.toLowerCase());
            if (isReferenced) {
                // This table is referenced in the query
                filtered[key] = value;
            }
            else if (isObjectNamespace(value)) {
                // Check if any child tables are referenced
                const filteredChild = filterSchemaByTableRefs(value, tableRefs);
                if (Object.keys(filteredChild).length > 0) {
                    filtered[key] = filteredChild;
                }
            }
        }
        return filtered;
    }
    // For other namespace types, return as-is (they might contain columns from referenced tables)
    return schema;
}
/**
 * Creates a hover tooltip extension for SQL
 */
export function sqlHover(config = {}) {
    const { schema = {}, keywords = {}, hoverTime = 300, enableKeywords = true, enableTables = true, enableColumns = true, enableFuzzySearch = true, parser = new NodeSqlParser(), tooltipRender, tooltipRenderers = {}, } = config;
    let keywordsPromise = null;
    return hoverTooltip(async (view, pos, side) => {
        const { from, to, text } = view.state.doc.lineAt(pos);
        let start = pos;
        let end = pos;
        if (keywordsPromise === null) {
            keywordsPromise =
                typeof keywords === "function" ? keywords(view) : Promise.resolve(keywords);
        }
        const resolvedKeywords = await keywordsPromise;
        // Find word boundaries (including dots for table.column syntax)
        while (start > from && /[\w.]/.test(text[start - from - 1] ?? ""))
            start--;
        while (end < to && /[\w.]/.test(text[end - from] ?? ""))
            end++;
        // Validate pointer position within word
        if ((start === pos && side < 0) || (end === pos && side > 0)) {
            return null;
        }
        const word = text.slice(start - from, end - from).toLowerCase();
        if (!word || word.length === 0) {
            return null;
        }
        const resolvedSchema = typeof schema === "function" ? schema(view) : schema;
        let createData = null;
        debug(`hover word: '${word}'`);
        // Implement preference order:
        // 1. Look in keywords if it exists
        // 2. Look for it in SQLNamespace as is
        // 3. If neither, look in SQLNamespace and try to guess (fuzzy match)
        // Step 1: If no namespace match, try keywords
        if (!createData && enableKeywords && resolvedKeywords[word]) {
            debug("keywordResult", word, resolvedKeywords[word]);
            const keywordData = { keyword: word, info: resolvedKeywords[word] };
            createData = {
                word,
                view,
                pos,
                tooltipType: "keyword",
                keywordData,
            };
        }
        // Step 2: Try to resolve directly in SQLNamespace (query-aware)
        if (!createData && (enableTables || enableColumns) && resolvedSchema) {
            // Get the current SQL query to filter schema by referenced tables
            const currentQuery = view.state.doc.toString();
            const tableList = await parser.extractTableReferences(currentQuery);
            const tableRefs = new Set(tableList.map((table) => table.toLowerCase()));
            // Filter schema to only include tables referenced in the current query
            const filteredSchema = filterSchemaByTableRefs(resolvedSchema, tableRefs);
            // Try to resolve in the filtered schema first (query-aware)
            let namespaceResult = resolveNamespaceItem(filteredSchema, word, {
                enableFuzzySearch,
            });
            // If no result in filtered schema and no tables were found in query,
            // fall back to the full schema to show any relevant information
            if (!namespaceResult && tableRefs.size === 0) {
                namespaceResult = resolveNamespaceItem(resolvedSchema, word, {
                    enableFuzzySearch,
                });
            }
            if (namespaceResult) {
                debug("namespaceResult (query-aware)", word, namespaceResult, "tableRefs:", Array.from(tableRefs));
                const namespaceData = {
                    item: namespaceResult,
                    word,
                    resolvedSchema: tableRefs.size > 0 ? filteredSchema : resolvedSchema,
                };
                createData = {
                    word,
                    view,
                    pos,
                    tooltipType: "namespace",
                    namespaceData,
                };
            }
            else {
                debug("No namespace item found for:", word);
            }
        }
        // Step 3: Fuzzy matching is handled by resolveNamespaceItem if enableFuzzySearch is true
        if (!createData) {
            return null;
        }
        return {
            pos: start,
            end,
            above: true,
            create(createView) {
                // Priority 1: Custom tooltipRender function
                if (tooltipRender) {
                    const customElement = tooltipRender(word, createView, pos);
                    if (customElement) {
                        return { dom: customElement };
                    }
                }
                // Priority 2: Custom renderers and default renderers
                let tooltipContent = null;
                if (createData.tooltipType === "keyword" && createData.keywordData) {
                    tooltipContent = tooltipRenderers.keyword
                        ? tooltipRenderers.keyword(createData.keywordData)
                        : createKeywordTooltip(createData.keywordData);
                }
                else if (createData.tooltipType === "namespace" && createData.namespaceData) {
                    const namespaceData = createData.namespaceData;
                    const { semanticType } = namespaceData.item;
                    if (semanticType === "table" && tooltipRenderers.table) {
                        tooltipContent = tooltipRenderers.table(namespaceData);
                    }
                    else if (semanticType === "column" && tooltipRenderers.column) {
                        tooltipContent = tooltipRenderers.column(namespaceData);
                    }
                    else if ((semanticType === "database" ||
                        semanticType === "schema" ||
                        semanticType === "namespace") &&
                        tooltipRenderers.namespace) {
                        tooltipContent = tooltipRenderers.namespace(namespaceData);
                    }
                    else {
                        // Fallback to default renderer
                        tooltipContent = createNamespaceTooltip(namespaceData.item);
                    }
                }
                if (!tooltipContent) {
                    return { dom: document.createElement("div") };
                }
                const dom = document.createElement("div");
                dom.className = "cm-sql-hover-tooltip";
                dom.innerHTML = tooltipContent;
                return { dom };
            },
        };
    }, { hoverTime });
}
/**
 * Creates HTML content for namespace-resolved items
 */
function createNamespaceTooltip(item) {
    const pathStr = item.path.join(".");
    const name = item.completion?.label || item.value || item.path[item.path.length - 1] || "unknown";
    let html = `<div class="sql-hover-${item.semanticType}">`;
    html += `<div class="sql-hover-header"><strong>${name}</strong> <span class="sql-hover-type">${item.semanticType}</span></div>`;
    // Add semantic-specific descriptions and information
    switch (item.semanticType) {
        case "database":
            html += `<div class="sql-hover-description">Database${item.completion?.detail ? `: ${item.completion.detail}` : ""}</div>`;
            if (item.namespace) {
                const childCount = countNamespaceChildren(item.namespace);
                if (childCount > 0) {
                    html += `<div class="sql-hover-children">Contains ${childCount} schema${childCount !== 1 ? "s" : ""}</div>`;
                }
            }
            break;
        case "schema":
            html += `<div class="sql-hover-description">Schema${item.completion?.detail ? `: ${item.completion.detail}` : ""}</div>`;
            if (pathStr) {
                html += `<div class="sql-hover-path"><strong>Path:</strong> <code>${pathStr}</code></div>`;
            }
            if (item.namespace) {
                const childCount = countNamespaceChildren(item.namespace);
                if (childCount > 0) {
                    html += `<div class="sql-hover-children">Contains ${childCount} table${childCount !== 1 ? "s" : ""}</div>`;
                }
            }
            break;
        case "table":
            html += `<div class="sql-hover-description">Table${item.completion?.detail ? `: ${item.completion.detail}` : ""}</div>`;
            if (pathStr) {
                const pathParts = item.path;
                if (pathParts.length > 1) {
                    html += `<div class="sql-hover-path"><strong>Schema:</strong> <code>${pathParts.slice(0, -1).join(".")}</code></div>`;
                }
            }
            // Show column information for tables
            if (item.namespace && isArrayNamespace(item.namespace)) {
                const columns = item.namespace;
                if (columns.length > 0) {
                    html += `<div class="sql-hover-columns"><strong>Columns (${columns.length}):</strong><br>`;
                    const displayColumns = columns.slice(0, 8);
                    const columnNames = displayColumns.map((col) => typeof col === "string" ? col : col.label);
                    html += columnNames.map((col) => `<code>${col}</code>`).join(", ");
                    if (columns.length > 8) {
                        html += `, <em>and ${columns.length - 8} more...</em>`;
                    }
                    html += `</div>`;
                }
            }
            break;
        case "column":
            html += `<div class="sql-hover-description">Column${item.completion?.detail ? `: ${item.completion.detail}` : ""}</div>`;
            if (pathStr) {
                const pathParts = item.path;
                if (pathParts.length > 1) {
                    html += `<div class="sql-hover-path"><strong>Table:</strong> <code>${pathParts.slice(0, -1).join(".")}</code></div>`;
                }
            }
            break;
        default:
            html += `<div class="sql-hover-description">Namespace${item.completion?.detail ? `: ${item.completion.detail}` : ""}</div>`;
            if (pathStr) {
                html += `<div class="sql-hover-path"><strong>Path:</strong> <code>${pathStr}</code></div>`;
            }
            if (item.namespace) {
                const childCount = countNamespaceChildren(item.namespace);
                if (childCount > 0) {
                    html += `<div class="sql-hover-children">Contains ${childCount} item${childCount !== 1 ? "s" : ""}</div>`;
                }
            }
            break;
    }
    // Add completion-specific info if available
    if (item.completion?.info && typeof item.completion.info === "string") {
        html += `<div class="sql-hover-info">${item.completion.info}</div>`;
    }
    html += `</div>`;
    return html;
}
/**
 * Helper function to count children in a namespace
 */
function countNamespaceChildren(namespace) {
    if (Array.isArray(namespace)) {
        return namespace.length;
    }
    else if (typeof namespace === "object" && namespace !== null) {
        if ("self" in namespace && "children" in namespace) {
            return 1 + countNamespaceChildren(namespace.children);
        }
        else {
            return Object.keys(namespace).length;
        }
    }
    return 0;
}
/**
 * Creates HTML content for keyword tooltips
 * Renders metadata as tags if present
 */
function createKeywordTooltip(opts) {
    const { keyword, info } = opts;
    let html = `<div class="sql-hover-keyword">`;
    html += `<div class="sql-hover-header"><strong>${keyword.toUpperCase()}</strong> <span class="sql-hover-type">keyword</span></div>`;
    html += `<div class="sql-hover-description">${info.description}</div>`;
    if (info.syntax) {
        html += `<div class="sql-hover-syntax"><strong>Syntax:</strong> <code>${info.syntax}</code></div>`;
    }
    if (info.example) {
        html += `<div class="sql-hover-example"><strong>Example:</strong><br><code>${info.example}</code></div>`;
    }
    if (info.metadata && typeof info.metadata === "object" && Object.keys(info.metadata).length > 0) {
        html += `<div class="sql-hover-metadata">`;
        for (const [key, value] of Object.entries(info.metadata)) {
            html += `<span class="sql-hover-tag" title="${key}">${value}</span> `;
        }
        html += `</div>`;
    }
    html += `</div>`;
    return html;
}
/**
 * Creates HTML content for table tooltips
 */
function createTableTooltip(opts) {
    const { tableName, columns, metadata } = opts;
    let html = `<div class="sql-hover-table">`;
    html += `<div class="sql-hover-header"><strong>${tableName}</strong> <span class="sql-hover-type">table</span></div>`;
    html += `<div class="sql-hover-description">Table with ${columns.length} column${columns.length !== 1 ? "s" : ""}</div>`;
    if (columns.length > 0) {
        html += `<div class="sql-hover-columns"><strong>Columns:</strong><br>`;
        const displayColumns = columns.slice(0, 10); // Show max 10 columns
        html += displayColumns.map((col) => `<code>${col}</code>`).join(", ");
        if (columns.length > 10) {
            html += `, <em>and ${columns.length - 10} more...</em>`;
        }
        html += `</div>`;
    }
    if (metadata && typeof metadata === "object" && Object.keys(metadata).length > 0) {
        html += `<div class="sql-hover-metadata">`;
        for (const [key, value] of Object.entries(metadata)) {
            html += `<span class="sql-hover-tag" title="${key}">${value}</span> `;
        }
        html += `</div>`;
    }
    html += `</div>`;
    return html;
}
/**
 * Creates HTML content for column tooltips
 */
function createColumnTooltip(opts) {
    const { tableName, columnName, schema, metadata } = opts;
    let html = `<div class="sql-hover-column">`;
    html += `<div class="sql-hover-header"><strong>${columnName}</strong> <span class="sql-hover-type">column</span></div>`;
    html += `<div class="sql-hover-description">Column in table <code>${tableName}</code></div>`;
    const allColumns = schema[tableName];
    if (allColumns && allColumns.length > 1) {
        const otherColumns = allColumns.filter((col) => col !== columnName);
        if (otherColumns.length > 0) {
            html += `<div class="sql-hover-related"><strong>Other columns in ${tableName}:</strong><br>`;
            const displayColumns = otherColumns.slice(0, 8); // Show max 8 other columns
            html += displayColumns.map((col) => `<code>${col}</code>`).join(", ");
            if (otherColumns.length > 8) {
                html += `, <em>and ${otherColumns.length - 8} more...</em>`;
            }
            html += `</div>`;
        }
    }
    if (metadata && typeof metadata === "object" && Object.keys(metadata).length > 0) {
        html += `<div class="sql-hover-metadata">`;
        for (const [key, value] of Object.entries(metadata)) {
            html += `<span class="sql-hover-tag" title="${key}">${value}</span> `;
        }
        html += `</div>`;
    }
    html += `</div>`;
    return html;
}
export const DefaultSqlTooltipRenders = {
    keyword: createKeywordTooltip,
    table: createTableTooltip,
    column: createColumnTooltip,
    namespace: createNamespaceTooltip,
};
/**
 * Default CSS styles for hover tooltips
 */
export const defaultSqlHoverTheme = (theme = "light") => {
    // Theme-dependent color variables
    const lightTheme = {
        tooltipBg: "#ffffff",
        tooltipBorder: "#e5e7eb",
        tooltipText: "#374151",
        tooltipTypeBg: "#f3f4f6",
        tooltipTypeText: "#6b7280",
        tooltipChildren: "#6b7280",
        codeBg: "#f9fafb",
        codeText: "#1f2937",
        strong: "#111827",
        em: "#6b7280",
        header: "#111827",
        info: "#374151",
        related: "#374151",
        path: "#374151",
        example: "#374151",
        columns: "#374151",
        syntax: "#374151",
    };
    const darkTheme = {
        tooltipBg: "#1f2937",
        tooltipBorder: "#374151",
        tooltipText: "#f9fafb",
        tooltipTypeBg: "#374151",
        tooltipTypeText: "#9ca3af",
        tooltipChildren: "#9ca3af",
        codeBg: "#374151",
        codeText: "#f3f4f6",
        strong: "#ffffff",
        em: "#9ca3af",
        header: "#ffffff",
        info: "#d1d5db",
        related: "#d1d5db",
        path: "#d1d5db",
        example: "#d1d5db",
        columns: "#d1d5db",
        syntax: "#d1d5db",
    };
    const colors = theme === "dark" ? darkTheme : lightTheme;
    return EditorView.theme({
        ".cm-sql-hover-tooltip": {
            padding: "8px 12px",
            backgroundColor: colors.tooltipBg,
            border: `1px solid ${colors.tooltipBorder}`,
            borderRadius: "6px",
            boxShadow: "0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)",
            fontSize: "13px",
            lineHeight: "1.4",
            maxWidth: "320px",
            fontFamily: "system-ui, -apple-system, sans-serif",
            color: colors.tooltipText,
        },
        ".cm-sql-hover-tooltip .sql-hover-header": {
            marginBottom: "6px",
            display: "flex",
            alignItems: "center",
            gap: "6px",
            color: colors.header,
        },
        ".cm-sql-hover-tooltip .sql-hover-type": {
            fontSize: "11px",
            padding: "2px 6px",
            backgroundColor: colors.tooltipTypeBg,
            color: colors.tooltipTypeText,
            borderRadius: "4px",
            fontWeight: "500",
        },
        ".cm-sql-hover-tooltip .sql-hover-description": {
            color: colors.info,
            marginBottom: "8px",
        },
        ".cm-sql-hover-tooltip .sql-hover-syntax": {
            marginBottom: "8px",
            color: colors.syntax,
        },
        ".cm-sql-hover-tooltip .sql-hover-example": {
            marginBottom: "4px",
            color: colors.example,
        },
        ".cm-sql-hover-tooltip .sql-hover-columns": {
            marginBottom: "4px",
            color: colors.columns,
        },
        ".cm-sql-hover-tooltip .sql-hover-related": {
            marginBottom: "4px",
            color: colors.related,
        },
        ".cm-sql-hover-tooltip .sql-hover-path": {
            marginBottom: "4px",
            color: colors.path,
        },
        ".cm-sql-hover-tooltip .sql-hover-info": {
            marginBottom: "4px",
            color: colors.info,
        },
        ".cm-sql-hover-tooltip .sql-hover-children": {
            marginBottom: "4px",
            color: colors.tooltipChildren,
            fontSize: "12px",
        },
        ".cm-sql-hover-tooltip code": {
            backgroundColor: colors.codeBg,
            padding: "1px 4px",
            borderRadius: "3px",
            fontSize: "12px",
            fontFamily: "ui-monospace, 'SF Mono', 'Monaco', 'Cascadia Code', 'Roboto Mono', monospace",
            color: colors.codeText,
        },
        ".cm-sql-hover-tooltip strong": {
            fontWeight: "600",
            color: colors.strong,
        },
        ".cm-sql-hover-tooltip em": {
            fontStyle: "italic",
            color: colors.em,
        },
    });
};
//# sourceMappingURL=hover.js.map