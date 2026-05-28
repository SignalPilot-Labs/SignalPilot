import { StateEffect, StateField } from "@codemirror/state";
// Effect to update resources
export const updateResources = StateEffect.define();
// StateField to track resources
export const resourcesField = StateField.define({
    create() {
        return new Map();
    },
    update(oldResources, tr) {
        let updated = false;
        let newResources = oldResources;
        for (const e of tr.effects) {
            if (e.is(updateResources)) {
                if (!updated) {
                    newResources = new Map(oldResources);
                    updated = true;
                }
                for (const [resourceURI, resource] of e.value) {
                    newResources.set(resourceURI, resource);
                }
            }
        }
        return newResources;
    },
});
export const mcpOptionsField = StateField.define({
    create() {
        return {
            onResourceClick: undefined,
            onResourceMouseOver: undefined,
            onResourceMouseOut: undefined,
            onPromptSubmit: undefined,
        };
    },
    update(value) {
        return value;
    },
});
// Effect to update prompts
export const updatePrompts = StateEffect.define();
// StateField to track prompts
export const promptsField = StateField.define({
    create() {
        return new Map();
    },
    update(oldPrompts, tr) {
        let updated = false;
        let newPrompts = oldPrompts;
        for (const e of tr.effects) {
            if (e.is(updatePrompts)) {
                if (!updated) {
                    newPrompts = new Map(oldPrompts);
                    updated = true;
                }
                for (const [name, prompt] of e.value) {
                    newPrompts.set(name, prompt);
                }
            }
        }
        return newPrompts;
    },
});
//# sourceMappingURL=state.js.map