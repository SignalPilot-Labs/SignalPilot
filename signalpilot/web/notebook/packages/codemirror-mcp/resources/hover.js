import { hoverTooltip } from "@codemirror/view";
import { resourcesField } from "../state.js";
import { matchAllURIs } from "../utils.js";
export function createDefaultTooltip(resource) {
    const dom = document.createElement("div");
    dom.className = "cm-tooltip-cursor";
    const title = document.createElement("div");
    title.className = "cm-tooltip-cursor-title";
    title.textContent = `${resource.name} (${resource.uri})`;
    dom.appendChild(title);
    if (resource.description) {
        const description = document.createElement("div");
        description.className = "cm-tooltip-cursor-description";
        description.textContent = resource.description;
        dom.appendChild(description);
    }
    if (resource.mimeType) {
        const mimeType = document.createElement("div");
        mimeType.className = "cm-tooltip-cursor-mimetype";
        mimeType.textContent = resource.mimeType;
        dom.appendChild(mimeType);
    }
    return { dom };
}
export function findResourceAtPosition(text, pos, resources, lineStart = 0) {
    for (const match of matchAllURIs(text)) {
        const start = lineStart + match.index;
        const end = start + match[0].length;
        if (pos >= start && pos <= end) {
            const uri = match[0].slice(1); // Remove @ prefix
            const resource = resources.get(uri);
            if (resource) {
                return { resource, start, end };
            }
        }
    }
    return null;
}
export function hoverResource(options) {
    return hoverTooltip((view, pos) => {
        const { from, text } = view.state.doc.lineAt(pos);
        const resources = view.state.field(resourcesField);
        // Fallback: try to find resource in the document text (works for non-decorated resources)
        const result = findResourceAtPosition(text, pos, resources, from);
        if (!result)
            return null;
        return {
            pos: result.start,
            end: result.end,
            above: true,
            create() {
                const createTooltip = options.createTooltip ?? createDefaultTooltip;
                return createTooltip(result.resource);
            },
        };
    });
}
//# sourceMappingURL=hover.js.map