import type { Completion } from "@codemirror/autocomplete";
import type * as LSP from "vscode-languageserver-protocol";
interface ConvertCompletionOptions {
    allowHTMLContent: boolean;
    useSnippetOnCompletion: boolean;
    hasResolveProvider: boolean;
    resolveItem: (item: LSP.CompletionItem) => Promise<LSP.CompletionItem>;
    markdownRenderer?: (markdown: string) => string;
}
/**
 * Converts an LSP snippet to a CodeMirror snippet
 */
export declare function convertSnippet(snippet: string): string;
/**
 * Converts an LSP completion item to a CodeMirror completion item
 */
export declare function convertCompletionItem(item: LSP.CompletionItem, options: ConvertCompletionOptions): Completion;
export declare function sortCompletionItems(items: LSP.CompletionItem[], matchBefore: string | undefined, language: string): LSP.CompletionItem[];
export {};
//# sourceMappingURL=completion.d.ts.map