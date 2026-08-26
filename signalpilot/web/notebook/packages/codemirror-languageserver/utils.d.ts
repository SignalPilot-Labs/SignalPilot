import type { Text } from "@codemirror/state";
import type { ChangeSet } from "@codemirror/state";
import type { EditorView } from "@codemirror/view";
import type * as LSP from "vscode-languageserver-protocol";
export declare function posToOffset(doc: Text, pos: {
    line: number;
    character: number;
}): number | undefined;
export declare function posToOffsetOrZero(doc: Text, pos: {
    line: number;
    character: number;
}): number;
export declare function offsetToPos(doc: Text, offset: number): {
    character: number;
    line: number;
};
/**
 * Render markdown to HTML
 */
export declare function renderMarkdown(markdown: string): string;
export declare function formatContents(contents: LSP.MarkupContent | LSP.MarkedString | LSP.MarkedString[] | undefined, markdownRenderer?: typeof renderMarkdown): string;
/**
 * Finds the longest common prefix among an array of strings.
 *
 * @param strs - Array of strings to analyze
 * @returns The longest common prefix string
 */
export declare function longestCommonPrefix(strs: string[]): string;
/**
 * Analyzes completion items to generate a regex pattern for matching prefixes.
 * Used to determine what text should be considered part of the current token
 * when filtering completion items.
 *
 * @param items - Array of LSP completion items to analyze
 * @returns A RegExp object that matches anywhere in a string
 */
export declare function prefixMatch(items: LSP.CompletionItem[]): RegExp | undefined;
export declare function isLSPTextEdit(textEdit?: LSP.TextEdit | LSP.InsertReplaceEdit): textEdit is LSP.TextEdit;
export declare function isLSPMarkupContent(contents: LSP.MarkupContent | LSP.MarkedString | LSP.MarkedString[]): contents is LSP.MarkupContent;
export declare function showErrorMessage(view: EditorView, message: string): void;
export declare function isEmptyDocumentation(documentation: LSP.MarkupContent | LSP.MarkedString | LSP.MarkedString[] | undefined): boolean;
/**
 * Map a `ChangeSet` into `TextDocumentContentChangeEvent[]` to be applied by an LSP
 * @param doc The doc before applying the ChangeSet
 * @param changes The `ChangeSet` to map
 */
export declare function eventsFromChangeSet(doc: Text, changes: ChangeSet): LSP.TextDocumentContentChangeEvent[];
//# sourceMappingURL=utils.d.ts.map