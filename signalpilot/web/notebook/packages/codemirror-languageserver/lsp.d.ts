import type { autocompletion } from "@codemirror/autocomplete";
import type { hoverTooltip } from "@codemirror/view";
import type { Transport } from "@open-rpc/client-js/build/transports/Transport.js";
import type * as LSP from "vscode-languageserver-protocol";
export interface LSPRequestMap {
    initialize: [LSP.InitializeParams, LSP.InitializeResult];
    "textDocument/hover": [LSP.HoverParams, LSP.Hover];
    "textDocument/completion": [
        LSP.CompletionParams,
        LSP.CompletionItem[] | LSP.CompletionList | null
    ];
    "completionItem/resolve": [LSP.CompletionItem, LSP.CompletionItem];
    "textDocument/definition": [
        LSP.DefinitionParams,
        LSP.Definition | LSP.DefinitionLink[] | null
    ];
    "textDocument/codeAction": [
        LSP.CodeActionParams,
        (LSP.Command | LSP.CodeAction)[] | null
    ];
    "textDocument/rename": [LSP.RenameParams, LSP.WorkspaceEdit | null];
    "textDocument/prepareRename": [
        LSP.PrepareRenameParams,
        LSP.Range | LSP.PrepareRenameResult | null
    ];
    "textDocument/signatureHelp": [
        LSP.SignatureHelpParams,
        LSP.SignatureHelp | null
    ];
}
export interface LSPNotifyMap {
    initialized: LSP.InitializedParams;
    "textDocument/didChange": LSP.DidChangeTextDocumentParams;
    "textDocument/didOpen": LSP.DidOpenTextDocumentParams;
}
export interface LSPEventMap {
    "textDocument/publishDiagnostics": LSP.PublishDiagnosticsParams;
}
export type Notification = {
    [key in keyof LSPEventMap]: {
        jsonrpc: "2.0";
        id?: null | undefined;
        method: key;
        params: LSPEventMap[key];
    };
}[keyof LSPEventMap];
/**
 * Options for configuring the language server client
 */
export interface LanguageServerClientOptions {
    /** The root URI of the workspace, used for LSP initialization */
    rootUri: string;
    /** List of workspace folders to send to the language server */
    workspaceFolders: LSP.WorkspaceFolder[] | null;
    /** Transport mechanism for communicating with the language server */
    transport: Transport;
    /** Timeout for requests to the language server */
    timeout?: number;
    /**
     * Client capabilities to send to the server during initialization.
     * Can be an object or a function that modifies the default capabilities.
     */
    capabilities?: LSP.InitializeParams["capabilities"] | ((defaultCapabilities: LSP.InitializeParams["capabilities"]) => LSP.InitializeParams["capabilities"]);
    /** Additional initialization options to send to the language server */
    initializationOptions?: LSP.InitializeParams["initializationOptions"];
    getWorkspaceConfiguration?: (params: LSP.ConfigurationParams) => LSP.LSPAny[];
}
/**
 * Keyboard shortcut configuration for LSP features
 */
export interface KeyboardShortcuts {
    /** Keyboard shortcut for rename operations (default: F2) */
    rename?: string;
    /** Keyboard shortcut for go to definition (default: Ctrl/Cmd+Click) */
    goToDefinition?: string;
    /** Keyboard shortcut for signature help (default: Ctrl/Cmd+Shift+Space) */
    signatureHelp?: string;
}
/**
 * Result of a definition lookup operation
 */
export interface DefinitionResult {
    /** URI of the target document containing the definition */
    uri: string;
    /** Range in the document where the definition is located */
    range: LSP.Range;
    /** Whether the definition is in a different file than the current document */
    isExternalDocument: boolean;
}
export interface FeatureOptions {
    /** Whether to enable diagnostic messages (default: true) */
    diagnosticsEnabled?: boolean;
    /** Whether to enable hover tooltips (default: true) */
    hoverEnabled?: boolean;
    /** Whether to enable code completion (default: true) */
    completionEnabled?: boolean;
    /** Whether to enable go-to-definition (default: true) */
    definitionEnabled?: boolean;
    /** Whether to enable rename functionality (default: true) */
    renameEnabled?: boolean;
    /** Whether to enable code actions (default: true) */
    codeActionsEnabled?: boolean;
    /** Whether to enable signature help (default: true) */
    signatureHelpEnabled?: boolean;
    /** Whether to show signature help while typing (default: false) */
    signatureActivateOnTyping?: boolean;
    /** Additional options for signature help */
    signatureHelpOptions?: {
        /** Position of the signature help tooltip (default: "below") */
        position?: "above" | "below";
    };
}
/**
 * Complete options for configuring the language server integration
 */
export interface LanguageServerOptions extends FeatureOptions {
    /** Pre-configured language server client instance or options */
    client: LanguageServerClient;
    /** Whether to allow HTML content in hover tooltips and other UI elements */
    allowHTMLContent?: boolean;
    /** Whether to prefer snippet insertion for completions when available */
    useSnippetOnCompletion?: boolean;
    /** URI of the current document being edited. If not provided, must be passed via the documentUri facet. */
    documentUri?: string;
    /** Language identifier (e.g., 'typescript', 'javascript', etc.). If not provided, must be passed via the languageId facet. */
    languageId?: string;
    /** Configuration for keyboard shortcuts */
    keyboardShortcuts?: KeyboardShortcuts;
    /** Callback triggered when a go-to-definition action is performed */
    onGoToDefinition?: (result: DefinitionResult) => void;
    /**
     * Configuration for the completion feature.
     * If not provided, the default completion config will be used.
     */
    completionConfig?: Parameters<typeof autocompletion>[0];
    /**
     * Configuration for the hover feature.
     * If not provided, the default hover config will be used.
     */
    hoverConfig?: Parameters<typeof hoverTooltip>[1];
    /**
     * Regular expression for determining when to show completions.
     * Default is to show completions when typing a word, after a dot, or after a slash.
     */
    completionMatchBefore?: RegExp;
    /**
     * Whether to send incremental changes to the language server.
     * @default true
     */
    sendIncrementalChanges?: boolean;
    /**
     * Specify an alternative renderer for markdown content.
     * @param markdown Markdown string content.
     * @returns The rendered HTML content.
     */
    markdownRenderer?: (markdown: string) => string;
}
/**
 * Options for connecting to a language server via WebSocket
 */
export interface LanguageServerWebsocketOptions extends Omit<LanguageServerOptions, "client">, Omit<LanguageServerClientOptions, "transport"> {
    /** WebSocket URI for connecting to the language server */
    serverUri: `ws://${string}` | `wss://${string}`;
}
export declare class LanguageServerClient {
    ready: boolean;
    capabilities: LSP.ServerCapabilities | null;
    initializePromise: Promise<void>;
    private rootUri;
    private workspaceFolders;
    private timeout;
    private transport;
    private requestManager;
    private client;
    private initializationOptions;
    clientCapabilities: LanguageServerClientOptions["capabilities"];
    private notificationListeners;
    constructor({ rootUri, workspaceFolders, transport, initializationOptions, capabilities, timeout, getWorkspaceConfiguration, }: LanguageServerClientOptions);
    protected getInitializationOptions(): LSP.InitializeParams["initializationOptions"];
    initialize(): Promise<void>;
    close(): void;
    textDocumentDidOpen(params: LSP.DidOpenTextDocumentParams): Promise<LSP.DidOpenTextDocumentParams>;
    textDocumentDidChange(params: LSP.DidChangeTextDocumentParams): Promise<LSP.DidChangeTextDocumentParams>;
    textDocumentHover(params: LSP.HoverParams): Promise<LSP.Hover>;
    textDocumentCompletion(params: LSP.CompletionParams): Promise<LSP.CompletionItem[] | LSP.CompletionList | null>;
    completionItemResolve(item: LSP.CompletionItem): Promise<LSP.CompletionItem>;
    textDocumentDefinition(params: LSP.DefinitionParams): Promise<LSP.Definition | LSP.LocationLink[] | null>;
    textDocumentCodeAction(params: LSP.CodeActionParams): Promise<(LSP.Command | LSP.CodeAction)[] | null>;
    textDocumentRename(params: LSP.RenameParams): Promise<LSP.WorkspaceEdit | null>;
    textDocumentPrepareRename(params: LSP.PrepareRenameParams): Promise<LSP.PrepareRenameResult | null>;
    textDocumentSignatureHelp(params: LSP.SignatureHelpParams): Promise<LSP.SignatureHelp | null>;
    onNotification(listener: (n: Notification) => void): () => boolean;
    protected request<K extends keyof LSPRequestMap>(method: K, params: LSPRequestMap[K][0], timeout: number): Promise<LSPRequestMap[K][1]>;
    protected notify<K extends keyof LSPNotifyMap>(method: K, params: LSPNotifyMap[K]): Promise<LSPNotifyMap[K]>;
    protected processNotification(notification: Notification): void;
}
//# sourceMappingURL=lsp.d.ts.map