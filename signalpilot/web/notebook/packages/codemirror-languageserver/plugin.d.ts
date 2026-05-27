import { EditorView, type Tooltip } from "@codemirror/view";
import { CompletionTriggerKind } from "vscode-languageserver-protocol";
import type { CompletionContext, CompletionResult } from "@codemirror/autocomplete";
import { type Extension, StateField } from "@codemirror/state";
import type { PluginValue, ViewUpdate } from "@codemirror/view";
import type * as LSP from "vscode-languageserver-protocol";
import type { PublishDiagnosticsParams } from "vscode-languageserver-protocol";
import { type DefinitionResult, type FeatureOptions, LanguageServerClient, type LanguageServerOptions, type LanguageServerWebsocketOptions, type Notification } from "./lsp.js";
/**
 * StateEffect for setting or clearing the signature help tooltip
 */
export declare const setSignatureHelpTooltip: import("@codemirror/state").StateEffectType<Tooltip | null>;
/**
 * StateField that manages the signature help tooltip state
 * Uses CodeMirror's showTooltip for proper lifecycle management
 */
export declare const signatureHelpTooltipField: StateField<Tooltip | null>;
export declare const suppressSignatureHelp: import("@codemirror/state").AnnotationType<boolean>;
export declare class LanguageServerPlugin implements PluginValue {
    private documentVersion;
    private pluginId;
    client: LanguageServerClient;
    documentUri: string;
    languageId: string;
    view: EditorView;
    allowHTMLContent: boolean;
    useSnippetOnCompletion: boolean;
    sendIncrementalChanges: boolean;
    featureOptions: Required<FeatureOptions>;
    onGoToDefinition: ((result: DefinitionResult) => void) | undefined;
    markdownRenderer: (markdown: string) => string;
    private disposeListener?;
    constructor(opts: {
        client: LanguageServerClient;
        documentUri: string;
        languageId: string;
        view: EditorView;
        featureOptions: Required<FeatureOptions>;
        sendIncrementalChanges?: boolean;
        allowHTMLContent?: boolean;
        useSnippetOnCompletion?: boolean;
        onGoToDefinition?: (result: DefinitionResult) => void;
        markdownRenderer?: (markdown: string) => string;
    });
    update({ state, docChanged, startState: { doc }, changes, }: ViewUpdate): void;
    destroy(): void;
    initialize({ documentText }: {
        documentText: string;
    }): Promise<void>;
    sendChanges(contentChanges: LSP.TextDocumentContentChangeEvent[]): Promise<void>;
    requestDiagnostics(view: EditorView): void;
    requestHoverTooltip(view: EditorView, { line, character }: {
        line: number;
        character: number;
    }): Promise<Tooltip | null>;
    requestCompletion(context: CompletionContext, { line, character }: {
        line: number;
        character: number;
    }, { triggerKind, triggerCharacter, }: {
        triggerKind: CompletionTriggerKind;
        triggerCharacter: string | undefined;
    }): Promise<CompletionResult | null>;
    requestDefinition(view: EditorView, { line, character }: {
        line: number;
        character: number;
    }): Promise<DefinitionResult | undefined>;
    processNotification(notification: Notification): void;
    private lastSeenDiagnosticsVersion;
    processDiagnostics(params: PublishDiagnosticsParams): Promise<void>;
    /**
     * Adds diagnostics to the current state
     */
    private addDiagnostics;
    private clearDiagnostics;
    private requestCodeActions;
    requestRename(view: EditorView, { line, character }: {
        line: number;
        character: number;
    }): Promise<void>;
    /**
     * Request signature help from the language server
     * @param view The editor view
     * @param position The cursor position
     * @returns A tooltip with the signature help information or null if not available
     */
    requestSignatureHelp(view: EditorView, { line, character, }: {
        line: number;
        character: number;
    }, triggerCharacter?: string | undefined): Promise<Tooltip | null>;
    /**
     * Shows a signature help tooltip at the specified position
     */
    showSignatureHelpTooltip(view: EditorView, pos: number, triggerCharacter?: string): Promise<void>;
    /**
     * Creates the main tooltip container for signature help
     */
    private createTooltipContainer;
    /**
     * Creates the signature element with parameter highlighting
     */
    private createSignatureElement;
    /**
     * Applies parameter highlighting using a range approach
     */
    private applyRangeHighlighting;
    /**
     * Creates the documentation element for signatures
     */
    private createDocumentationElement;
    /**
     * Creates the parameter documentation element
     */
    private createParameterDocElement;
    /**
     * Fallback implementation of prepareRename.
     * We try to find the word at the cursor position and return the range of the word.
     */
    private prepareRenameFallback;
    /**
     * Apply workspace edit from rename operation
     * @param view The editor view
     * @param edit The workspace edit to apply
     * @returns True if changes were applied successfully
     */
    protected applyRenameEdit(view: EditorView, edit: LSP.WorkspaceEdit | null): Promise<boolean>;
}
export declare function languageServer(options: LanguageServerWebsocketOptions): Extension[];
export declare function languageServerWithClient(options: LanguageServerOptions): Extension[];
export declare function getCompletionTriggerKind(context: CompletionContext, triggerCharacters: string[], matchBeforePattern?: RegExp): {
    triggerKind: 1 | 2;
    triggerCharacter: string | undefined;
} | null;
/**
 * Calculates the trigger position for signature help based on inserted text.
 *
 * This function finds the first trigger character in the inserted text and returns
 * the position right after it. This is important for handling auto-bracket completion
 * where "()" is inserted at once - we want the position after "(", not after ")".
 *
 * @param insertedText The text that was inserted
 * @param fromB The start position of the insertion in the document
 * @param triggerChars Array of characters that trigger signature help (e.g., ["(", ","])
 * @returns Object with triggerPos and triggerCharacter, or null if no trigger found
 */
export declare function getSignatureHelpTriggerPosition(insertedText: string, fromB: number, triggerChars: string[]): {
    triggerPos: number;
    triggerCharacter: string;
} | null;
/**
 * Calculates the parentheses balance in a string.
 * Used to determine if the cursor is inside a function call.
 *
 * @param text The text to scan for parentheses
 * @returns The balance: positive means inside parens, zero/negative means outside
 */
export declare function getParenthesesBalance(text: string): number;
/**
 * Checks if the cursor is inside a function call by counting parentheses balance.
 * Scans backwards from cursor position up to maxLinesBack lines.
 *
 * @param doc The CodeMirror document
 * @param cursorPos The current cursor position
 * @param maxLinesBack Maximum number of lines to scan backwards (default: 20)
 * @returns true if cursor appears to be inside a function call
 */
export declare function isCursorInsideFunctionCall(doc: {
    lineAt: (pos: number) => {
        number: number;
        from: number;
    };
    line: (n: number) => {
        from: number;
    };
    sliceString: (from: number, to: number) => string;
}, cursorPos: number, maxLinesBack?: number): boolean;
//# sourceMappingURL=plugin.d.ts.map