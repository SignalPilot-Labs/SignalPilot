import { Client, RequestManager, } from "@open-rpc/client-js";
const TIMEOUT = 10000;
export class LanguageServerClient {
    ready;
    capabilities;
    initializePromise;
    rootUri;
    workspaceFolders;
    timeout;
    transport;
    requestManager;
    client;
    initializationOptions;
    clientCapabilities;
    notificationListeners = new Set();
    constructor({ rootUri, workspaceFolders, transport, initializationOptions, capabilities, timeout = TIMEOUT, getWorkspaceConfiguration, }) {
        this.rootUri = rootUri;
        this.workspaceFolders = workspaceFolders;
        this.transport = transport;
        this.initializationOptions = initializationOptions;
        this.clientCapabilities = capabilities;
        this.timeout = timeout;
        this.ready = false;
        this.capabilities = null;
        this.requestManager = new RequestManager([this.transport]);
        this.client = new Client(this.requestManager);
        this.client.onNotification((data) => {
            this.processNotification(data);
        });
        const webSocketTransport = this.transport;
        if (webSocketTransport?.connection) {
            webSocketTransport.connection.addEventListener("message", 
            // @ts-ignore
            (message) => {
                const data = JSON.parse(message.data);
                if (data.method === "workspace/configuration" &&
                    getWorkspaceConfiguration) {
                    webSocketTransport.connection.send(JSON.stringify({
                        jsonrpc: "2.0",
                        id: data.id,
                        result: getWorkspaceConfiguration(data.params),
                    }));
                    // XXX(hjr265): Need a better way to do this. Relevant issue:
                    // https://github.com/FurqanSoftware/codemirror-languageserver/issues/9
                }
                else if (data.method && data.id) {
                    webSocketTransport.connection.send(JSON.stringify({
                        jsonrpc: "2.0",
                        id: data.id,
                        result: null,
                    }));
                }
            });
        }
        this.initializePromise = this.initialize();
    }
    getInitializationOptions() {
        const defaultClientCapabilities = {
            textDocument: {
                hover: {
                    dynamicRegistration: true,
                    contentFormat: ["markdown", "plaintext"],
                },
                moniker: {},
                synchronization: {
                    dynamicRegistration: true,
                    willSave: false,
                    didSave: false,
                    willSaveWaitUntil: false,
                },
                codeAction: {
                    dynamicRegistration: true,
                    codeActionLiteralSupport: {
                        codeActionKind: {
                            valueSet: [
                                "",
                                "quickfix",
                                "refactor",
                                "refactor.extract",
                                "refactor.inline",
                                "refactor.rewrite",
                                "source",
                                "source.organizeImports",
                            ],
                        },
                    },
                    resolveSupport: {
                        properties: ["edit"],
                    },
                },
                completion: {
                    dynamicRegistration: true,
                    completionItem: {
                        snippetSupport: true,
                        commitCharactersSupport: true,
                        documentationFormat: ["markdown", "plaintext"],
                        deprecatedSupport: false,
                        preselectSupport: false,
                    },
                    contextSupport: false,
                },
                signatureHelp: {
                    dynamicRegistration: true,
                    signatureInformation: {
                        documentationFormat: ["markdown", "plaintext"],
                    },
                },
                declaration: {
                    dynamicRegistration: true,
                    linkSupport: true,
                },
                definition: {
                    dynamicRegistration: true,
                    linkSupport: true,
                },
                typeDefinition: {
                    dynamicRegistration: true,
                    linkSupport: true,
                },
                implementation: {
                    dynamicRegistration: true,
                    linkSupport: true,
                },
                rename: {
                    dynamicRegistration: true,
                    prepareSupport: true,
                },
            },
            workspace: {
                didChangeConfiguration: {
                    dynamicRegistration: true,
                },
            },
        };
        const defaultOptions = {
            capabilities: this.clientCapabilities
                ? typeof this.clientCapabilities === "function"
                    ? this.clientCapabilities(defaultClientCapabilities)
                    : this.clientCapabilities
                : defaultClientCapabilities,
            initializationOptions: this.initializationOptions,
            processId: null,
            rootUri: this.rootUri,
            workspaceFolders: this.workspaceFolders,
        };
        return defaultOptions;
    }
    async initialize() {
        const { capabilities } = await this.request("initialize", this.getInitializationOptions(), this.timeout * 3);
        this.capabilities = capabilities;
        this.notify("initialized", {});
        this.ready = true;
    }
    close() {
        this.client.close();
    }
    textDocumentDidOpen(params) {
        return this.notify("textDocument/didOpen", params);
    }
    textDocumentDidChange(params) {
        return this.notify("textDocument/didChange", params);
    }
    async textDocumentHover(params) {
        return await this.request("textDocument/hover", params, this.timeout);
    }
    async textDocumentCompletion(params) {
        return await this.request("textDocument/completion", params, this.timeout);
    }
    async completionItemResolve(item) {
        return await this.request("completionItem/resolve", item, this.timeout);
    }
    async textDocumentDefinition(params) {
        return await this.request("textDocument/definition", params, this.timeout);
    }
    async textDocumentCodeAction(params) {
        return await this.request("textDocument/codeAction", params, this.timeout);
    }
    async textDocumentRename(params) {
        return await this.request("textDocument/rename", params, this.timeout);
    }
    async textDocumentPrepareRename(params) {
        return await this.request("textDocument/prepareRename", params, this.timeout);
    }
    async textDocumentSignatureHelp(params) {
        return await this.request("textDocument/signatureHelp", params, this.timeout);
    }
    onNotification(listener) {
        this.notificationListeners.add(listener);
        return () => this.notificationListeners.delete(listener);
    }
    request(method, params, timeout) {
        return this.client.request({ method, params }, timeout);
    }
    notify(method, params) {
        return this.client.notify({ method, params });
    }
    processNotification(notification) {
        this.notificationListeners.forEach((l) => l(notification));
    }
}
//# sourceMappingURL=lsp.js.map