import type { Completion, CompletionSource } from "@codemirror/autocomplete";
import type { Resource } from "./resource.js";
export declare const resourceCompletion: (getResources: () => Promise<Resource[]>, formatResource?: (resource: Resource) => Partial<Completion>) => CompletionSource;
//# sourceMappingURL=completion.d.ts.map