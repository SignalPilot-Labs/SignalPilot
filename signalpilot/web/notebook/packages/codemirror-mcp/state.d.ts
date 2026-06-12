import { type StateEffectType, StateField } from "@codemirror/state";
import type { Prompt, PromptMessage } from "@modelcontextprotocol/sdk/types.js";
import type { Resource } from "./resources/resource.js";
type ResourceURI = string;
type ResourceMap = Map<ResourceURI, Resource>;
export declare const updateResources: StateEffectType<ResourceMap>;
export declare const resourcesField: StateField<ResourceMap>;
interface MCPHandlers {
    onResourceClick?: (resource: Resource) => void;
    onResourceMouseOver?: (resource: Resource) => void;
    onResourceMouseOut?: (resource: Resource) => void;
    onPromptSubmit?: (opts: {
        messages: PromptMessage[];
    }) => void;
}
export declare const mcpOptionsField: StateField<MCPHandlers>;
type PromptMap = Map<string, Prompt>;
export declare const updatePrompts: StateEffectType<PromptMap>;
export declare const promptsField: StateField<PromptMap>;
export {};
//# sourceMappingURL=state.d.ts.map