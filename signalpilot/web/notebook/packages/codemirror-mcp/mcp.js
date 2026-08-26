import { autocompletion } from "@codemirror/autocomplete";
import { GetPromptResultSchema, ListPromptsResultSchema, } from "@modelcontextprotocol/sdk/types.js";
import { MCPResourceProvider } from "./mcp/mcp-provider.js";
import { resourceCompletion } from "./resources/completion.js";
import { resourceDecorations } from "./resources/decoration.js";
import { hoverResource } from "./resources/hover.js";
import { resourceInputFilter } from "./resources/input-filter.js";
import { toMCPResource } from "./resources/resource.js";
import { mcpOptionsField, promptsField, resourcesField, updatePrompts } from "./state.js";
import { resourceTheme } from "./theme.js";
async function handlePromptCompletion({ word, connected, client, logger, context, }) {
    if (!word)
        return null;
    if (word.from === word.to && !context.explicit)
        return null;
    if (!connected) {
        logger?.error("MCP client is not connected");
        return null;
    }
    logger?.log("Fetching prompts from MCP server");
    try {
        // Fetch prompts from MCP server
        const response = await client.request({ method: "prompts/list" }, ListPromptsResultSchema);
        const prompts = response.prompts;
        // TODO: Implement prompt with args
        // Not implemented yet, ideally looks a bit like slack completions
        // /read_table [table_name]
        // /read_table [table_name] [column_name]
        // /read_table [table_name] [column_name] [row_id]
        const promptWithoutArgs = prompts.filter((prompt) => !prompt.args || Object.keys(prompt.args).length === 0);
        if (promptWithoutArgs.length === 0) {
            return null;
        }
        const effects = updatePrompts.of(new Map(promptWithoutArgs.map((prompt) => [prompt.name, prompt])));
        if (context.view) {
            context.view.dispatch({ effects });
        }
        logger?.log(`Got ${prompts.length} prompts from MCP server`);
        // // Convert prompts to completion items
        const options = prompts.map((prompt) => ({
            label: `/${prompt.name}`,
            displayLabel: prompt.name,
            detail: prompt.description,
            type: "keyword",
            boost: prompt.description ? 100 : 0,
            apply: async (view, _completion, _from, _to) => {
                const mcpOptions = view.state.field(mcpOptionsField);
                if (!mcpOptions.onPromptSubmit) {
                    logger?.error("No onPromptSubmit callback set");
                    throw new Error("No onPromptSubmit callback set");
                }
                // Load the prompt template
                const promptResult = await client.request({ method: "prompts/get", params: { name: prompt.name } }, GetPromptResultSchema);
                mcpOptions.onPromptSubmit(promptResult);
            },
        }));
        return {
            from: word.from,
            options,
        };
    }
    catch (error) {
        logger?.error("Failed to fetch MCP prompts:", error);
        return null;
    }
}
export function mcpExtension(options) {
    const logger = options.logger;
    const resourceProvider = new MCPResourceProvider(options.transport, options.clientOptions, logger);
    const completion = autocompletion({
        override: [
            async (context) => {
                // Handle resource completions (@)
                const resourceWord = context.matchBefore(/@(\w+)?/);
                if (resourceWord) {
                    const connected = await resourceProvider.isConnected();
                    if (!connected) {
                        logger?.error("MCP client is not connected");
                        return null;
                    }
                    logger?.log("Fetching resources from MCP server");
                    return resourceCompletion(() => resourceProvider.getResources())(context);
                }
                // Handle prompt completions (/)
                const promptWord = context.matchBefore(/\/(\w+)?/);
                if (promptWord) {
                    return handlePromptCompletion({
                        connected: await resourceProvider.isConnected(),
                        resourceProvider,
                        client: resourceProvider.getClient(),
                        logger,
                        context,
                        word: promptWord,
                    });
                }
                return null;
            },
        ],
    });
    const adaptResource = (callback) => {
        if (!callback)
            return undefined;
        return (mcpResource) => {
            callback(toMCPResource(mcpResource));
        };
    };
    return [
        resourcesField,
        promptsField,
        completion,
        resourceTheme,
        hoverResource(options.hoverOptions ?? {}),
        resourceDecorations,
        resourceInputFilter,
        mcpOptionsField.init(() => ({
            onResourceClick: adaptResource(options.onResourceClick),
            onResourceMouseOver: adaptResource(options.onResourceMouseOver),
            onResourceMouseOut: adaptResource(options.onResourceMouseOut),
            onPromptSubmit: options.onPromptSubmit,
        })),
    ];
}
//# sourceMappingURL=mcp.js.map