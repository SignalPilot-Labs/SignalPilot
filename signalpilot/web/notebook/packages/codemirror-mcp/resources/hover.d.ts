import { type TooltipView } from "@codemirror/view";
import type { Resource } from "./resource.js";
export declare function createDefaultTooltip(resource: Resource): TooltipView;
export interface ResourceMatch {
    resource: Resource;
    start: number;
    end: number;
}
export declare function findResourceAtPosition(text: string, pos: number, resources: Map<string, Resource>, lineStart?: number): ResourceMatch | null;
export interface HoverResourceOptions {
    createTooltip?: (resource: Resource) => TooltipView;
}
export declare function hoverResource(options: HoverResourceOptions): import("@codemirror/state").Extension & {
    active: import("@codemirror/state").StateField<readonly import("@codemirror/view").Tooltip[]>;
};
//# sourceMappingURL=hover.d.ts.map