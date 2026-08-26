import { updateResources } from "../state.js";
export const resourceCompletion = (getResources, formatResource) => {
    return async (context) => {
        // Handle resource completions (@)
        const resourceWord = context.matchBefore(/@(\w+)?/);
        if (!resourceWord)
            return null;
        if (resourceWord.from === resourceWord.to && !context.explicit)
            return null;
        const resources = await getResources();
        if (resources.length === 0) {
            return null;
        }
        const effects = updateResources.of(new Map(resources.map((resource) => [resource.uri, resource])));
        if (context.view) {
            context.view.dispatch({ effects });
        }
        // Convert resources to completion items
        const options = resources.map((resource) => ({
            label: `@${resource.name}`,
            displayLabel: resource.name,
            detail: resource.uri,
            info: resource.description || undefined,
            type: resource.mimeType ? "constant" : "variable",
            boost: resource.description ? 100 : 0,
            // Override with custom formatter
            ...formatResource?.(resource),
            apply: (view, _completion, from, to) => {
                view.dispatch({
                    changes: { from, to, insert: `@${resource.uri} ` },
                });
            },
        }));
        return {
            from: resourceWord.from,
            options,
        };
    };
};
//# sourceMappingURL=completion.js.map