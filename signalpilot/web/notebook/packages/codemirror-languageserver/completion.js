import { insertCompletionText, snippet } from "@codemirror/autocomplete";
import { CompletionItemKind } from "vscode-languageserver-protocol";
import { formatContents, isEmptyDocumentation, isLSPTextEdit, posToOffset, posToOffsetOrZero, } from "./utils.js";
const CompletionItemKindMap = Object.fromEntries(Object.entries(CompletionItemKind).map(([key, value]) => [value, key]));
var InsertTextFormat;
(function (InsertTextFormat) {
    InsertTextFormat.PlainText = 1;
    InsertTextFormat.Snippet = 2;
})(InsertTextFormat || (InsertTextFormat = {}));
/**
 * Converts an LSP snippet to a CodeMirror snippet
 */
export function convertSnippet(snippet) {
    // Remove double backslashes
    const result = snippet.replaceAll(/\\\\/g, "");
    // Braces are required in CodeMirror syntax
    return result.replaceAll(/(\$(\d+))/g, 
    // biome-ignore lint/style/useTemplate: reads better
    (_match, _p1, p2) => "${" + p2 + "}");
}
/**
 * Converts an LSP completion item to a CodeMirror completion item
 */
export function convertCompletionItem(item, options) {
    const { detail, labelDetails, label, kind, textEdit, insertText, documentation, additionalTextEdits, insertTextFormat, } = item;
    const completion = {
        label,
        detail: labelDetails?.detail || detail,
        apply(view, _completion, from, to) {
            if (textEdit && isLSPTextEdit(textEdit)) {
                view.dispatch(insertCompletionText(view.state, textEdit.newText, posToOffsetOrZero(view.state.doc, textEdit.range.start), posToOffsetOrZero(view.state.doc, textEdit.range.end)));
            }
            else {
                if (insertText &&
                    insertTextFormat === InsertTextFormat.Snippet &&
                    options.useSnippetOnCompletion) {
                    const applySnippet = snippet(convertSnippet(insertText));
                    applySnippet(view, null, from, to);
                }
                else {
                    // By default it is PlainText
                    view.dispatch(insertCompletionText(view.state, insertText || label, from, to));
                }
            }
            if (!additionalTextEdits) {
                return;
            }
            const sortedEdits = additionalTextEdits.sort(({ range: { end: a } }, { range: { end: b } }) => {
                if (posToOffsetOrZero(view.state.doc, a) <
                    posToOffsetOrZero(view.state.doc, b)) {
                    return 1;
                }
                if (posToOffsetOrZero(view.state.doc, a) >
                    posToOffsetOrZero(view.state.doc, b)) {
                    return -1;
                }
                return 0;
            });
            for (const textEdit of sortedEdits) {
                view.dispatch(view.state.update({
                    changes: {
                        from: posToOffsetOrZero(view.state.doc, textEdit.range.start),
                        to: posToOffset(view.state.doc, textEdit.range.end),
                        insert: textEdit.newText,
                    },
                }));
            }
        },
        type: kind && CompletionItemKindMap[kind].toLowerCase(),
    };
    // Support lazy loading of documentation through completionItem/resolve
    if (options.hasResolveProvider && options.resolveItem) {
        completion.info = async () => {
            try {
                const resolved = await options.resolveItem?.(item);
                const dom = document.createElement("div");
                dom.classList.add("documentation");
                const content = resolved?.documentation || documentation;
                if (!content) {
                    return null;
                }
                if (isEmptyDocumentation(content)) {
                    return null;
                }
                if (options.allowHTMLContent) {
                    dom.innerHTML = formatContents(content, options.markdownRenderer);
                }
                else {
                    dom.textContent = formatContents(content, options.markdownRenderer);
                }
                return dom;
            }
            catch (e) {
                console.error("Failed to resolve completion item:", e);
                if (isEmptyDocumentation(documentation)) {
                    return null;
                }
                // Fallback to existing documentation if resolve fails
                if (documentation) {
                    const dom = document.createElement("div");
                    dom.classList.add("documentation");
                    if (options.allowHTMLContent) {
                        dom.innerHTML = formatContents(documentation, options.markdownRenderer);
                    }
                    else {
                        dom.textContent = formatContents(documentation, options.markdownRenderer);
                    }
                    return dom;
                }
                return null;
            }
        };
    }
    else if (documentation) {
        // Fallback for servers without resolve support
        completion.info = () => {
            const dom = document.createElement("div");
            dom.classList.add("documentation");
            if (options.allowHTMLContent) {
                dom.innerHTML = formatContents(documentation, options.markdownRenderer);
            }
            else {
                dom.textContent = formatContents(documentation, options.markdownRenderer);
            }
            return dom;
        };
    }
    return completion;
}
export function sortCompletionItems(items, matchBefore, language) {
    const sortFunctions = [
        matchBefore ? prefixSortCompletion(matchBefore) : nameSortCompletion,
        language === "python" ? pythonSortCompletion : undefined,
    ].filter(Boolean);
    let result = items;
    // If we found a token that matches our completion pattern
    if (matchBefore) {
        const word = matchBefore.toLowerCase();
        // Only filter and sort for word characters
        if (/^\w+$/.test(word)) {
            // Filter items to only include those that start with the current word
            result = result.filter(({ label, filterText }) => {
                const text = filterText ?? label;
                return text.toLowerCase().startsWith(word);
            });
        }
    }
    for (const sortFunction of sortFunctions) {
        result.sort(sortFunction);
    }
    return result;
}
function prefixSortCompletion(prefix) {
    // Sort completion items:
    // 1. Prioritize items that start with the exact token text
    // 2. Otherwise maintain original order
    return (a, b) => {
        const aText = a.sortText ?? a.label;
        const bText = b.sortText ?? b.label;
        switch (true) {
            case aText.startsWith(prefix) && !bText.startsWith(prefix):
                return -1;
            case !aText.startsWith(prefix) && bText.startsWith(prefix):
                return 1;
        }
        return aText.localeCompare(bText);
    };
}
function nameSortCompletion(a, b) {
    const aText = a.sortText ?? a.label;
    const bText = b.sortText ?? b.label;
    return aText.localeCompare(bText);
}
function pythonSortCompletion(a, b) {
    // For python, if label ends with `=`, it should be sorted first
    const aIsAssignment = a.label.endsWith("=");
    const bIsAssignment = b.label.endsWith("=");
    if (aIsAssignment && !bIsAssignment) {
        return -1;
    }
    if (!aIsAssignment && bIsAssignment) {
        return 1;
    }
    return 0;
}
//# sourceMappingURL=completion.js.map