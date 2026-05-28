import { autocompletion } from "@codemirror/autocomplete";
import { forEachDiagnostic, setDiagnostics, } from "@codemirror/lint";
import { EditorView, ViewPlugin, hoverTooltip, keymap, showTooltip, } from "@codemirror/view";
import { WebSocketTransport } from "@open-rpc/client-js";
import { CompletionTriggerKind, DiagnosticSeverity, } from "vscode-languageserver-protocol";
import { StateEffect, StateField, Annotation, } from "@codemirror/state";
import { convertCompletionItem, sortCompletionItems } from "./completion.js";
import { documentUri, languageId } from "./config.js";
import { LanguageServerClient, } from "./lsp.js";
import { eventsFromChangeSet, formatContents, isEmptyDocumentation, offsetToPos, posToOffset, posToOffsetOrZero, prefixMatch, renderMarkdown, showErrorMessage, } from "./utils.js";
const logger = console.log;
// https://microsoft.github.io/language-server-protocol/specifications/specification-current/
function uniqueId() {
    return String(Date.now() + Math.random());
}
/**
 * StateEffect for setting or clearing the signature help tooltip
 */
export const setSignatureHelpTooltip = StateEffect.define();
/**
 * StateField that manages the signature help tooltip state
 * Uses CodeMirror's showTooltip for proper lifecycle management
 */
export const signatureHelpTooltipField = StateField.define({
    create: () => null,
    update(tooltip, tr) {
        for (const effect of tr.effects) {
            if (effect.is(setSignatureHelpTooltip)) {
                return effect.value;
            }
        }
        // Map tooltip position through document changes to keep it anchored correctly
        if (tooltip && tr.docChanged) {
            const newPos = tr.changes.mapPos(tooltip.pos);
            const newEnd = tooltip.end != null
                ? tr.changes.mapPos(tooltip.end)
                : undefined;
            return { ...tooltip, pos: newPos, end: newEnd };
        }
        return tooltip;
    },
    provide: (field) => showTooltip.from(field),
});
export const suppressSignatureHelp = Annotation.define();
const SIGNATURE_TOOLTIP_MAX_LINES_BACK = 20;
export class LanguageServerPlugin {
    documentVersion;
    pluginId;
    client;
    documentUri;
    languageId;
    view;
    allowHTMLContent;
    useSnippetOnCompletion;
    sendIncrementalChanges;
    featureOptions;
    onGoToDefinition;
    markdownRenderer;
    disposeListener;
    constructor(opts) {
        const { client, documentUri, languageId, view, featureOptions, sendIncrementalChanges = true, allowHTMLContent = false, useSnippetOnCompletion = false, onGoToDefinition, markdownRenderer = renderMarkdown, } = opts;
        this.documentVersion = 0;
        this.pluginId = uniqueId();
        this.client = client;
        this.documentUri = documentUri;
        this.languageId = languageId;
        this.view = view;
        this.allowHTMLContent = allowHTMLContent;
        this.useSnippetOnCompletion = useSnippetOnCompletion;
        this.sendIncrementalChanges = sendIncrementalChanges;
        this.featureOptions = featureOptions;
        this.onGoToDefinition = onGoToDefinition;
        this.markdownRenderer = markdownRenderer;
        this.disposeListener = client.onNotification(this.processNotification.bind(this));
        this.initialize({
            documentText: this.view.state.doc.toString(),
        });
    }
    update({ state, docChanged, startState: { doc }, changes, }) {
        if (!docChanged) {
            return;
        }
        if (this.sendIncrementalChanges) {
            this.sendChanges(eventsFromChangeSet(doc, changes));
        }
        else {
            this.sendChanges([{ text: state.doc.toString() }]);
        }
    }
    destroy() {
        this.disposeListener?.();
    }
    async initialize({ documentText }) {
        if (this.client.initializePromise) {
            await this.client.initializePromise;
        }
        await this.client.textDocumentDidOpen({
            textDocument: {
                uri: this.documentUri,
                languageId: this.languageId,
                text: documentText,
                version: this.documentVersion,
            },
        });
    }
    async sendChanges(contentChanges) {
        if (!this.client.ready) {
            return;
        }
        try {
            await this.client.textDocumentDidChange({
                textDocument: {
                    uri: this.documentUri,
                    version: ++this.documentVersion,
                },
                contentChanges,
            });
        }
        catch (e) {
            console.error(e);
        }
    }
    requestDiagnostics(view) {
        this.sendChanges([
            {
                text: view.state.doc.toString(),
            },
        ]);
    }
    async requestHoverTooltip(view, { line, character }) {
        // Check if hover is enabled
        if (!this.featureOptions.hoverEnabled) {
            return null;
        }
        if (!(this.client.ready && this.client.capabilities?.hoverProvider)) {
            return null;
        }
        const result = await this.client.textDocumentHover({
            textDocument: { uri: this.documentUri },
            position: { line, character },
        });
        if (!result) {
            return null;
        }
        const { contents, range } = result;
        let pos = posToOffset(view.state.doc, { line, character });
        let end;
        if (range) {
            pos = posToOffset(view.state.doc, range.start);
            end = posToOffset(view.state.doc, range.end);
        }
        if (pos == null) {
            return null;
        }
        if (isEmptyDocumentation(contents)) {
            return null;
        }
        const dom = document.createElement("div");
        dom.classList.add("documentation", "cm-lsp-hover-tooltip");
        if (this.allowHTMLContent) {
            dom.innerHTML = formatContents(contents, this.markdownRenderer);
        }
        else {
            dom.textContent = formatContents(contents, this.markdownRenderer);
        }
        return {
            pos,
            end,
            create: (_view) => ({ dom }),
            above: true,
        };
    }
    async requestCompletion(context, { line, character }, { triggerKind, triggerCharacter, }) {
        // Check if completion is enabled
        if (!this.featureOptions.completionEnabled) {
            return null;
        }
        if (!(this.client.ready && this.client.capabilities?.completionProvider)) {
            return null;
        }
        const result = await this.client.textDocumentCompletion({
            textDocument: { uri: this.documentUri },
            position: { line, character },
            context: {
                triggerKind,
                triggerCharacter,
            },
        });
        if (!result) {
            return null;
        }
        const items = "items" in result ? result.items : result;
        // Match is undefined if there are no common prefixes
        const match = prefixMatch(items);
        const token = match
            ? // Try prefix-based match, then fall back to general word match
                (context.matchBefore(match) ??
                    context.matchBefore(/[a-zA-Z0-9_]+/))
            : // Fallback to matching any word character
                context.matchBefore(/[a-zA-Z0-9_]+/);
        let { pos } = context;
        const sortedItems = sortCompletionItems(items, token?.text, this.languageId);
        // If we found a token that matches our completion pattern
        if (token) {
            // Set position to the start of the token
            pos = token.from;
        }
        const options = sortedItems.map((item) => {
            return convertCompletionItem(item, {
                allowHTMLContent: this.allowHTMLContent,
                useSnippetOnCompletion: this.useSnippetOnCompletion,
                hasResolveProvider: this.client.capabilities?.completionProvider
                    ?.resolveProvider ?? false,
                resolveItem: this.client.completionItemResolve.bind(this.client),
            });
        });
        return {
            from: pos,
            options,
            filter: false,
        };
    }
    async requestDefinition(view, { line, character }) {
        // Check if definition is enabled
        if (!this.featureOptions.definitionEnabled) {
            return;
        }
        if (!(this.client.ready && this.client.capabilities?.definitionProvider)) {
            return;
        }
        const result = await this.client.textDocumentDefinition({
            textDocument: { uri: this.documentUri },
            position: { line, character },
        });
        if (!result)
            return;
        const locations = Array.isArray(result) ? result : [result];
        if (locations.length === 0)
            return;
        // For now just handle the first location
        const location = locations[0];
        if (!location)
            return;
        const uri = "uri" in location ? location.uri : location.targetUri;
        const range = "range" in location ? location.range : location.targetRange;
        // Check if the definition is in a different document
        const isExternalDocument = uri !== this.documentUri;
        // Create the definition result
        const definitionResult = {
            uri,
            range,
            isExternalDocument,
        };
        // If it's the same document, update the selection
        if (!isExternalDocument) {
            view.dispatch(view.state.update({
                selection: {
                    anchor: posToOffsetOrZero(view.state.doc, range.start),
                    head: posToOffset(view.state.doc, range.end),
                },
            }));
        }
        if (this.onGoToDefinition) {
            this.onGoToDefinition(definitionResult);
        }
        return definitionResult;
    }
    processNotification(notification) {
        try {
            switch (notification.method) {
                case "textDocument/publishDiagnostics":
                    this.processDiagnostics(notification.params);
            }
        }
        catch (error) {
            logger(error);
        }
    }
    lastSeenDiagnosticsVersion = 0;
    async processDiagnostics(params) {
        if (params.uri !== this.documentUri) {
            return;
        }
        // If the version is newer, clear the diagnostics and update the last seen version
        if (params.version != null &&
            params.version > this.lastSeenDiagnosticsVersion) {
            this.lastSeenDiagnosticsVersion = params.version;
            this.clearDiagnostics();
        }
        // Check if diagnostics are enabled
        const diagEnabled = this.featureOptions.diagnosticsEnabled;
        if (!diagEnabled) {
            // Clear any existing diagnostics from this plugin if disabled
            this.clearDiagnostics();
            return;
        }
        const severityMap = {
            [DiagnosticSeverity.Error]: "error",
            [DiagnosticSeverity.Warning]: "warning",
            [DiagnosticSeverity.Information]: "info",
            [DiagnosticSeverity.Hint]: "info",
        };
        const diagnostics = params.diagnostics.map(async ({ range, message, severity, code, source }) => {
            const actions = await this.requestCodeActions(range, [
                code,
            ]);
            const codemirrorActions = actions?.map((action) => ({
                name: "command" in action &&
                    typeof action.command === "object"
                    ? action.command?.title || action.title
                    : action.title,
                apply: async () => {
                    if ("edit" in action && action.edit?.changes) {
                        const changes = action.edit.changes[this.documentUri];
                        if (!changes) {
                            return;
                        }
                        // Apply workspace edit
                        for (const change of changes) {
                            this.view.dispatch(this.view.state.update({
                                changes: {
                                    from: posToOffsetOrZero(this.view.state.doc, change.range.start),
                                    to: posToOffset(this.view.state.doc, change.range.end),
                                    insert: change.newText,
                                },
                            }));
                        }
                    }
                    if ("command" in action && action.command) {
                        // TODO: Implement command execution
                        // Execute command if present
                        logger("Executing command:", action.command);
                    }
                },
            }));
            const diagnostic = {
                from: posToOffsetOrZero(this.view.state.doc, range.start),
                to: posToOffsetOrZero(this.view.state.doc, range.end),
                severity: severityMap[severity ?? DiagnosticSeverity.Error],
                message: message,
                renderMessage: () => {
                    const dom = document.createElement("div");
                    dom.innerHTML = this.markdownRenderer(message);
                    return dom;
                },
                source: source || this.languageId,
                markClass: this.pluginId,
                actions: codemirrorActions,
            };
            return diagnostic;
        });
        const resolvedDiagnostics = await Promise.all(diagnostics);
        this.addDiagnostics(resolvedDiagnostics);
    }
    /**
     * Adds diagnostics to the current state
     */
    addDiagnostics(newDiagnostics) {
        if (newDiagnostics.length === 0) {
            return;
        }
        const state = this.view.state;
        // Get current diagnostics from the state
        const currentDiagnostics = [];
        forEachDiagnostic(state, (diagnostic) => {
            currentDiagnostics.push(diagnostic);
            return true;
        });
        // Sources
        const uniqueSources = new Set(newDiagnostics
            .map((diagnostic) => diagnostic.source)
            .filter(Boolean));
        // Filter out diagnostics from the same source
        const diagnosticsFromOtherSources = newDiagnostics.filter((diagnostic) => {
            return !uniqueSources.has(diagnostic.source);
        });
        this.view.dispatch(setDiagnostics(state, [
            ...diagnosticsFromOtherSources,
            ...newDiagnostics,
        ]));
    }
    clearDiagnostics() {
        this.view.dispatch(setDiagnostics(this.view.state, []));
    }
    async requestCodeActions(range, diagnosticCodes) {
        // Check if code actions are enabled
        if (!this.featureOptions.codeActionsEnabled) {
            return null;
        }
        if (!(this.client.ready && this.client.capabilities?.codeActionProvider)) {
            return null;
        }
        return await this.client.textDocumentCodeAction({
            textDocument: { uri: this.documentUri },
            range,
            context: {
                diagnostics: [
                    {
                        range,
                        code: diagnosticCodes[0],
                        source: this.languageId,
                        message: "",
                    },
                ],
            },
        });
    }
    async requestRename(view, { line, character }) {
        // Check if rename is enabled
        if (!this.featureOptions.renameEnabled) {
            return;
        }
        if (!this.client.ready) {
            showErrorMessage(view, "Language server not ready");
            return;
        }
        if (!this.client.capabilities?.renameProvider) {
            showErrorMessage(view, "Rename not supported by language server");
            return;
        }
        try {
            // First check if rename is possible at this position
            const prepareResult = await this.client
                .textDocumentPrepareRename({
                textDocument: { uri: this.documentUri },
                position: { line, character },
            })
                .catch(() => {
                // In case prepareRename is not supported,
                // we fallback to the default implementation
                return this.prepareRenameFallback(view, {
                    line,
                    character,
                });
            });
            if (!prepareResult || "defaultBehavior" in prepareResult) {
                showErrorMessage(view, "Cannot rename this symbol");
                return;
            }
            // Create popup input
            const popup = document.createElement("div");
            popup.className = "cm-rename-popup";
            popup.style.cssText =
                "position: absolute; padding: 4px; background: white; border: 1px solid #ddd; box-shadow: 0 2px 8px rgba(0,0,0,.15); z-index: 99;";
            const input = document.createElement("input");
            input.type = "text";
            input.style.cssText =
                "width: 200px; padding: 4px; border: 1px solid #ddd;";
            // Get current word as default value
            const range = "range" in prepareResult ? prepareResult.range : prepareResult;
            const from = posToOffset(view.state.doc, range.start);
            if (from == null) {
                return;
            }
            const to = posToOffset(view.state.doc, range.end);
            input.value = view.state.doc.sliceString(from, to);
            popup.appendChild(input);
            // Position the popup near the word
            const coords = view.coordsAtPos(from);
            if (!coords)
                return;
            popup.style.left = `${coords.left}px`;
            popup.style.top = `${coords.bottom + 5}px`;
            // Handle input
            const handleRename = async () => {
                const newName = input.value.trim();
                if (!newName) {
                    showErrorMessage(view, "New name cannot be empty");
                    popup.remove();
                    return;
                }
                if (newName === input.defaultValue) {
                    popup.remove();
                    return;
                }
                try {
                    const edit = await this.client.textDocumentRename({
                        textDocument: { uri: this.documentUri },
                        position: { line, character },
                        newName,
                    });
                    await this.applyRenameEdit(view, edit);
                }
                catch (error) {
                    showErrorMessage(view, `Rename failed: ${error instanceof Error ? error.message : "Unknown error"}`);
                }
                finally {
                    popup.remove();
                }
            };
            input.addEventListener("keydown", (e) => {
                if (e.key === "Enter") {
                    handleRename();
                }
                else if (e.key === "Escape") {
                    popup.remove();
                }
                e.stopPropagation(); // Prevent editor handling
            });
            // Handle clicks outside
            const handleOutsideClick = (e) => {
                if (!popup.contains(e.target)) {
                    popup.remove();
                    document.removeEventListener("mousedown", handleOutsideClick);
                }
            };
            document.addEventListener("mousedown", handleOutsideClick);
            // Add to DOM
            document.body.appendChild(popup);
            input.focus();
            input.select();
        }
        catch (error) {
            showErrorMessage(view, `Rename failed: ${error instanceof Error ? error.message : "Unknown error"}`);
        }
    }
    /**
     * Request signature help from the language server
     * @param view The editor view
     * @param position The cursor position
     * @returns A tooltip with the signature help information or null if not available
     */
    async requestSignatureHelp(view, { line, character, }, triggerCharacter = undefined) {
        // Check if signature help is enabled
        if (!(this.featureOptions.signatureHelpEnabled &&
            this.client.ready &&
            this.client.capabilities?.signatureHelpProvider)) {
            return null;
        }
        try {
            // Request signature help
            const result = await this.client.textDocumentSignatureHelp({
                textDocument: { uri: this.documentUri },
                position: { line, character },
                context: {
                    isRetrigger: false,
                    triggerKind: 1, // Invoked
                    triggerCharacter,
                },
            });
            if (!result?.signatures || result.signatures.length === 0) {
                return null;
            }
            // Create the tooltip container
            const dom = this.createTooltipContainer();
            // Get active signature
            const activeSignatureIndex = result.activeSignature ?? 0;
            const activeSignature = result.signatures[activeSignatureIndex] || result.signatures[0];
            if (!activeSignature) {
                return null;
            }
            const activeParameterIndex = result.activeParameter ?? activeSignature.activeParameter ?? 0;
            // Create and add signature display element
            const signatureElement = this.createSignatureElement(activeSignature, activeParameterIndex);
            dom.appendChild(signatureElement);
            // Add documentation if available
            if (activeSignature.documentation) {
                dom.appendChild(this.createDocumentationElement(activeSignature.documentation));
            }
            // Add parameter documentation if available
            const activeParam = activeSignature.parameters?.[activeParameterIndex];
            if (activeParam?.documentation) {
                dom.appendChild(this.createParameterDocElement(activeParam.documentation));
            }
            // Position tooltip at cursor
            const pos = posToOffset(view.state.doc, { line, character });
            if (pos == null) {
                return null;
            }
            return {
                pos,
                end: pos,
                create: (_view) => ({ dom }),
                above: this.featureOptions.signatureHelpOptions?.position ===
                    "above",
            };
        }
        catch (error) {
            console.error("Signature help error:", error);
            return null;
        }
    }
    /**
     * Shows a signature help tooltip at the specified position
     */
    async showSignatureHelpTooltip(view, pos, triggerCharacter) {
        const tooltip = await this.requestSignatureHelp(view, offsetToPos(view.state.doc, pos), triggerCharacter);
        // Dispatch the tooltip (or null to clear) via StateEffect
        view.dispatch({
            effects: setSignatureHelpTooltip.of(tooltip),
        });
    }
    /**
     * Creates the main tooltip container for signature help
     */
    createTooltipContainer() {
        const dom = document.createElement("div");
        dom.classList.add("cm-signature-help");
        dom.style.cssText = "padding: 6px; max-width: 400px;";
        return dom;
    }
    /**
     * Creates the signature element with parameter highlighting
     */
    createSignatureElement(signature, activeParameterIndex) {
        const signatureElement = document.createElement("div");
        signatureElement.classList.add("cm-signature");
        signatureElement.style.cssText =
            "font-family: monospace; margin-bottom: 4px;";
        if (!signature.label || typeof signature.label !== "string") {
            signatureElement.textContent = "Signature information unavailable";
            return signatureElement;
        }
        const signatureText = signature.label;
        const parameters = signature.parameters || [];
        // If there are no parameters or no active parameter, just show the signature text
        if (parameters.length === 0 || !parameters[activeParameterIndex]) {
            signatureElement.textContent = signatureText;
            return signatureElement;
        }
        // Handle parameter highlighting based on the parameter label type
        const paramLabel = parameters[activeParameterIndex].label;
        if (typeof paramLabel === "string") {
            // Simple string replacement
            if (this.allowHTMLContent) {
                signatureElement.innerHTML = signatureText.replace(paramLabel, `<strong class="cm-signature-active-param">${paramLabel}</strong>`);
            }
            else {
                signatureElement.textContent = signatureText.replace(paramLabel, `«${paramLabel}»`);
            }
        }
        else if (Array.isArray(paramLabel) && paramLabel.length === 2) {
            // Handle array format [startIndex, endIndex]
            this.applyRangeHighlighting(signatureElement, signatureText, paramLabel[0], paramLabel[1]);
        }
        else {
            signatureElement.textContent = signatureText;
        }
        return signatureElement;
    }
    /**
     * Applies parameter highlighting using a range approach
     */
    applyRangeHighlighting(element, text, startIndex, endIndex) {
        // Clear any existing content
        element.textContent = "";
        // Split the text into three parts: before, parameter, after
        const beforeParam = text.substring(0, startIndex);
        const param = text.substring(startIndex, endIndex);
        const afterParam = text.substring(endIndex);
        // Add the parts to the element
        element.appendChild(document.createTextNode(beforeParam));
        const paramSpan = document.createElement("span");
        paramSpan.classList.add("cm-signature-active-param");
        paramSpan.style.cssText =
            "font-weight: bold; text-decoration: underline;";
        paramSpan.textContent = param;
        element.appendChild(paramSpan);
        element.appendChild(document.createTextNode(afterParam));
    }
    /**
     * Creates the documentation element for signatures
     */
    createDocumentationElement(documentation) {
        const docsElement = document.createElement("div");
        docsElement.classList.add("cm-signature-docs");
        docsElement.style.cssText = "margin-top: 4px; color: #666;";
        const formattedContent = formatContents(documentation, this.markdownRenderer);
        if (this.allowHTMLContent) {
            docsElement.innerHTML = formattedContent;
        }
        else {
            docsElement.textContent = formattedContent;
        }
        return docsElement;
    }
    /**
     * Creates the parameter documentation element
     */
    createParameterDocElement(documentation) {
        const paramDocsElement = document.createElement("div");
        paramDocsElement.classList.add("cm-parameter-docs");
        paramDocsElement.style.cssText =
            "margin-top: 4px; font-style: italic; border-top: 1px solid #eee; padding-top: 4px;";
        const formattedContent = formatContents(documentation, this.markdownRenderer);
        if (this.allowHTMLContent) {
            paramDocsElement.innerHTML = formattedContent;
        }
        else {
            paramDocsElement.textContent = formattedContent;
        }
        return paramDocsElement;
    }
    /**
     * Fallback implementation of prepareRename.
     * We try to find the word at the cursor position and return the range of the word.
     */
    prepareRenameFallback(view, { line, character }) {
        const doc = view.state.doc;
        const lineText = doc.line(line + 1).text;
        const wordRegex = /\w+/g;
        let match;
        let start = character;
        let end = character;
        // Find all word matches in the line
        // biome-ignore lint/suspicious/noAssignInExpressions: <explanation>
        while ((match = wordRegex.exec(lineText)) !== null) {
            const matchStart = match.index;
            const matchEnd = match.index + match[0].length;
            // Check if cursor position is within or at the boundaries of this word
            if (character >= matchStart && character <= matchEnd) {
                start = matchStart;
                end = matchEnd;
                break;
            }
        }
        if (start === character && end === character) {
            return null; // No word found at cursor position
        }
        return {
            range: {
                start: {
                    line,
                    character: start,
                },
                end: {
                    line,
                    character: end,
                },
            },
            placeholder: lineText.slice(start, end),
        };
    }
    /**
     * Apply workspace edit from rename operation
     * @param view The editor view
     * @param edit The workspace edit to apply
     * @returns True if changes were applied successfully
     */
    async applyRenameEdit(view, edit) {
        if (!edit) {
            showErrorMessage(view, "No edit returned from language server");
            return false;
        }
        const changesMap = edit.changes ?? {};
        const documentChanges = edit.documentChanges ?? [];
        if (Object.keys(changesMap).length === 0 &&
            documentChanges.length === 0) {
            showErrorMessage(view, "No changes to apply");
            return false;
        }
        // Handle documentChanges (preferred) if available
        if (documentChanges.length > 0) {
            for (const docChange of documentChanges) {
                if ("textDocument" in docChange) {
                    // This is a TextDocumentEdit
                    const uri = docChange.textDocument.uri;
                    if (uri !== this.documentUri) {
                        showErrorMessage(view, "Multi-file rename not supported yet");
                        continue;
                    }
                    // Sort edits in reverse order to avoid position shifts
                    const sortedEdits = docChange.edits.sort((a, b) => {
                        const posA = posToOffset(view.state.doc, a.range.start);
                        const posB = posToOffset(view.state.doc, b.range.start);
                        return (posB ?? 0) - (posA ?? 0);
                    });
                    // Create a single transaction with all changes
                    const changes = sortedEdits.map((edit) => ({
                        from: posToOffset(view.state.doc, edit.range.start) ?? 0,
                        to: posToOffset(view.state.doc, edit.range.end) ?? 0,
                        insert: edit.newText,
                    }));
                    view.dispatch(view.state.update({ changes }));
                    return true;
                }
                // This is a CreateFile, RenameFile, or DeleteFile operation
                showErrorMessage(view, "File creation, deletion, or renaming operations not supported yet");
                return false;
            }
        }
        // Fall back to changes if documentChanges is not available
        else if (Object.keys(changesMap).length > 0) {
            // Apply all changes
            for (const [uri, changes] of Object.entries(changesMap)) {
                if (uri !== this.documentUri) {
                    showErrorMessage(view, "Multi-file rename not supported yet");
                    continue;
                }
                // Sort changes in reverse order to avoid position shifts
                const sortedChanges = changes.sort((a, b) => {
                    const posA = posToOffset(view.state.doc, a.range.start);
                    const posB = posToOffset(view.state.doc, b.range.start);
                    return (posB ?? 0) - (posA ?? 0);
                });
                // Create a single transaction with all changes
                const changeSpecs = sortedChanges.map((change) => ({
                    from: posToOffset(view.state.doc, change.range.start) ?? 0,
                    to: posToOffset(view.state.doc, change.range.end) ?? 0,
                    insert: change.newText,
                }));
                view.dispatch(view.state.update({ changes: changeSpecs }));
            }
        }
        return false;
    }
}
export function languageServer(options) {
    const { serverUri, ...rest } = options;
    return languageServerWithClient({
        ...rest,
        client: new LanguageServerClient({
            ...options,
            transport: new WebSocketTransport(serverUri),
        }),
    });
}
export function languageServerWithClient(options) {
    let plugin = null;
    const shortcuts = {
        rename: "F2",
        goToDefinition: "F12",
        signatureHelp: "Mod-Shift-Space",
        ...options.keyboardShortcuts,
    };
    const lsClient = options.client;
    const featuresOptions = {
        // Default to true
        diagnosticsEnabled: true,
        hoverEnabled: true,
        completionEnabled: true,
        definitionEnabled: true,
        renameEnabled: true,
        codeActionsEnabled: true,
        signatureHelpEnabled: true,
        signatureActivateOnTyping: false,
        signatureHelpOptions: {
            position: "below",
        },
        // Override defaults with provided options
        ...options,
    };
    // Create base extensions array
    const extensions = [
        ViewPlugin.define((view) => {
            plugin = new LanguageServerPlugin({
                client: lsClient,
                documentUri: options.documentUri ?? view.state.facet(documentUri),
                languageId: options.languageId ?? view.state.facet(languageId),
                view,
                featureOptions: featuresOptions,
                sendIncrementalChanges: options.sendIncrementalChanges,
                allowHTMLContent: options.allowHTMLContent,
                useSnippetOnCompletion: options.useSnippetOnCompletion,
                onGoToDefinition: options.onGoToDefinition,
                markdownRenderer: options.markdownRenderer,
            });
            return plugin;
        }),
    ];
    // Add shortcuts
    extensions.push(keymap.of([
        {
            key: shortcuts.signatureHelp,
            run: (view) => {
                if (!(plugin && featuresOptions.signatureHelpEnabled))
                    return false;
                const pos = view.state.selection.main.head;
                plugin.showSignatureHelpTooltip(view, pos);
                return true;
            },
        },
        {
            key: shortcuts.rename,
            run: (view) => {
                if (!(plugin && featuresOptions.renameEnabled))
                    return false;
                const pos = view.state.selection.main.head;
                plugin.requestRename(view, offsetToPos(view.state.doc, pos));
                return true;
            },
        },
        {
            key: shortcuts.goToDefinition,
            run: (view) => {
                if (!(plugin && featuresOptions.definitionEnabled))
                    return false;
                const pos = view.state.selection.main.head;
                plugin
                    .requestDefinition(view, offsetToPos(view.state.doc, pos))
                    .catch((error) => showErrorMessage(view, `Go to definition failed: ${error instanceof Error ? error.message : "Unknown error"}`));
                return true;
            },
        },
    ]));
    // Only add hover tooltip if enabled
    if (featuresOptions.hoverEnabled) {
        extensions.push(hoverTooltip((view, pos) => {
            if (plugin == null) {
                return null;
            }
            return plugin.requestHoverTooltip(view, offsetToPos(view.state.doc, pos));
        }, options.hoverConfig));
    }
    // Add signature help support if enabled
    if (featuresOptions.signatureHelpEnabled) {
        extensions.push(signatureHelpTooltipField);
        const hideSignatureHelpTooltip = (view) => {
            const tooltip = view.state.field(signatureHelpTooltipField);
            if (tooltip) {
                view.dispatch({
                    effects: setSignatureHelpTooltip.of(null),
                });
                return true;
            }
            return false;
        };
        // Dismiss signature help on mousedown
        extensions.push(EditorView.domEventHandlers({
            mousedown: (_, view) => {
                hideSignatureHelpTooltip(view);
                // Return false to let the click proceed normally
                return false;
            },
        }));
        extensions.push(keymap.of([
            {
                // Dismiss tooltip when closing paren is typed
                key: ")",
                run: (view) => {
                    hideSignatureHelpTooltip(view);
                    // Return false to let the character be inserted
                    return false;
                },
            },
            {
                // Or when Escape key is pressed
                key: "Escape",
                run: (view) => {
                    // Return what hideSignatureHelpTooltip returns
                    return hideSignatureHelpTooltip(view);
                },
            },
        ]));
        // Smart dismissal: detect when cursor moves outside the function call context
        // and dismiss the signature help tooltip.
        extensions.push(EditorView.updateListener.of((update) => {
            if (!(plugin && featuresOptions.signatureActivateOnTyping))
                return;
            const tooltip = update.state.field(signatureHelpTooltipField);
            if (!tooltip)
                return;
            // Only check when selection or doc changed
            const hasChange = update.selectionSet || update.docChanged;
            if (!hasChange)
                return;
            const cursorPos = update.state.selection.main.head;
            // If not inside any parentheses, dismiss
            if (!isCursorInsideFunctionCall(update.state.doc, cursorPos)) {
                hideSignatureHelpTooltip(update.view);
            }
        }));
        extensions.push(EditorView.updateListener.of(async (update) => {
            if (!(plugin && update.docChanged))
                return;
            if (update.transactions.some((tr) => tr.annotation(suppressSignatureHelp)))
                return;
            // Early exit if signature help capability is not supported
            if (!plugin.client.capabilities?.signatureHelpProvider)
                return;
            // Only proceed if signatureActivateOnTyping is enabled
            if (!featuresOptions.signatureActivateOnTyping)
                return;
            const triggerChars = plugin.client.capabilities
                .signatureHelpProvider.triggerCharacters || ["(", ","];
            // Check if changes include trigger characters
            const changes = update.changes;
            let triggerPos = -1;
            let triggerCharacter;
            changes.iterChanges((_fromA, _toA, fromB, _toB, inserted) => {
                if (triggerPos >= 0)
                    return; // Skip if already found a trigger
                const result = getSignatureHelpTriggerPosition(inserted.toString(), fromB, triggerChars);
                if (result) {
                    triggerPos = result.triggerPos;
                    triggerCharacter = result.triggerCharacter;
                }
            });
            if (triggerPos >= 0) {
                plugin.showSignatureHelpTooltip(update.view, triggerPos, triggerCharacter);
            }
        }));
    }
    // Only add autocompletion if enabled
    if (featuresOptions.completionEnabled) {
        extensions.push(autocompletion({
            ...options.completionConfig,
            override: [
                /**
                 * Completion source function that handles LSP-based autocompletion
                 *
                 * This function determines the appropriate trigger kind and character,
                 * checks if completion should be shown, and delegates to the plugin's
                 * requestCompletion method.
                 *
                 * @param context The completion context from CodeMirror
                 * @returns A CompletionResult or null if no completions are available
                 */
                async (context) => {
                    // Don't proceed if plugin isn't initialized
                    if (plugin == null) {
                        return null;
                    }
                    const { state, pos } = context;
                    const result = getCompletionTriggerKind(context, plugin.client.capabilities?.completionProvider
                        ?.triggerCharacters ?? [], options.completionMatchBefore);
                    if (result == null) {
                        return null;
                    }
                    // Request completions from the language server
                    return await plugin.requestCompletion(context, offsetToPos(state.doc, pos), result);
                },
                ...(options.completionConfig?.override || []),
            ],
        }));
    }
    // Add event handlers for rename and go to definition
    extensions.push(EditorView.domEventHandlers({
        click: (event, view) => {
            // Check if definition is enabled
            if (!featuresOptions.definitionEnabled)
                return;
            if (shortcuts.goToDefinition === "ctrlcmd" &&
                (event.ctrlKey || event.metaKey)) {
                const pos = view.posAtCoords({
                    x: event.clientX,
                    y: event.clientY,
                });
                if (pos && plugin) {
                    plugin
                        .requestDefinition(view, offsetToPos(view.state.doc, pos))
                        .catch((error) => showErrorMessage(view, `Go to definition failed: ${error instanceof Error ? error.message : "Unknown error"}`));
                    event.preventDefault();
                }
            }
        },
    }));
    return extensions;
}
export function getCompletionTriggerKind(context, triggerCharacters, matchBeforePattern) {
    const { state, pos, explicit } = context;
    const line = state.doc.lineAt(pos);
    // Determine trigger kind and character
    let triggerKind = CompletionTriggerKind.Invoked;
    let triggerCharacter;
    // Check if completion was triggered by a special character
    const prevChar = line.text[pos - line.from - 1] || "";
    const isTriggerChar = triggerCharacters?.includes(prevChar);
    if (!explicit && isTriggerChar) {
        triggerKind = CompletionTriggerKind.TriggerCharacter;
        triggerCharacter = prevChar;
    }
    // For manual invocation, only show completions when typing
    // Use the provided pattern or default to words, dots, commas, or slashes
    if (triggerKind === CompletionTriggerKind.Invoked &&
        !context.matchBefore(matchBeforePattern || /(\w+|\w+\.|\/|,)$/)) {
        return null;
    }
    return { triggerKind, triggerCharacter };
}
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
export function getSignatureHelpTriggerPosition(insertedText, fromB, triggerChars) {
    if (!insertedText)
        return null;
    for (const char of triggerChars) {
        const charIndex = insertedText.indexOf(char);
        if (charIndex !== -1) {
            return {
                // Position right after the trigger character
                triggerPos: fromB + charIndex + 1,
                triggerCharacter: char,
            };
        }
    }
    return null;
}
/**
 * Calculates the parentheses balance in a string.
 * Used to determine if the cursor is inside a function call.
 *
 * @param text The text to scan for parentheses
 * @returns The balance: positive means inside parens, zero/negative means outside
 */
export function getParenthesesBalance(text) {
    let balance = 0;
    for (const char of text) {
        if (char === "(")
            balance++;
        else if (char === ")")
            balance--;
    }
    return balance;
}
/**
 * Checks if the cursor is inside a function call by counting parentheses balance.
 * Scans backwards from cursor position up to maxLinesBack lines.
 *
 * @param doc The CodeMirror document
 * @param cursorPos The current cursor position
 * @param maxLinesBack Maximum number of lines to scan backwards (default: 20)
 * @returns true if cursor appears to be inside a function call
 */
export function isCursorInsideFunctionCall(doc, cursorPos, maxLinesBack = SIGNATURE_TOOLTIP_MAX_LINES_BACK) {
    const currentLine = doc.lineAt(cursorPos);
    const startLine = Math.max(1, currentLine.number - maxLinesBack);
    const startPos = doc.line(startLine).from;
    const textToScan = doc.sliceString(startPos, cursorPos);
    return getParenthesesBalance(textToScan) > 0;
}
//# sourceMappingURL=plugin.js.map