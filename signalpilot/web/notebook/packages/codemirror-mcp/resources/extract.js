import { resourcesField } from "../state.js";
import { matchAllURIs } from "../utils.js";
export function extractResources(view) {
    const text = view.state.doc.toString();
    const resources = view.state.field(resourcesField);
    const matches = [];
    for (const match of matchAllURIs(text)) {
        const start = match.index;
        const end = start + match[0].length;
        const uri = match[0].slice(1); // Remove @ prefix
        const resource = resources.get(uri);
        if (resource) {
            matches.push({ resource: resource, start, end });
        }
    }
    return matches;
}
//# sourceMappingURL=extract.js.map