import { Decoration, ViewPlugin, WidgetType, } from "@codemirror/view";
import { mcpOptionsField, resourcesField, updateResources } from "../state.js";
import { matchAllURIs } from "../utils.js";
// Widget for resource decoration
class ResourceWidget extends WidgetType {
    resource;
    view;
    constructor(resource, view) {
        super();
        this.resource = resource;
        this.view = view;
    }
    eq(other) {
        return other.resource.uri === this.resource.uri;
    }
    toDOM() {
        const wrap = document.createElement("span");
        wrap.className = "cm-resource-widget";
        wrap.textContent = `@${this.resource.name}`;
        const mcpOptions = this.view.state.field(mcpOptionsField, false);
        const onResourceClick = mcpOptions?.onResourceClick;
        const onResourceMouseOver = mcpOptions?.onResourceMouseOver;
        const onResourceMouseOut = mcpOptions?.onResourceMouseOut;
        if (onResourceClick) {
            wrap.style.cursor = "pointer";
            wrap.addEventListener("click", (e) => {
                e.preventDefault();
                e.stopPropagation();
                onResourceClick(this.resource);
            });
        }
        if (onResourceMouseOver) {
            wrap.addEventListener("mouseover", (e) => {
                e.preventDefault();
                e.stopPropagation();
                onResourceMouseOver(this.resource);
            });
        }
        if (onResourceMouseOut) {
            wrap.addEventListener("mouseout", (e) => {
                e.preventDefault();
                e.stopPropagation();
                onResourceMouseOut(this.resource);
            });
        }
        return wrap;
    }
}
// Widget for not found resources
class NotFoundResourceWidget extends WidgetType {
    uri;
    view;
    constructor(uri, view) {
        super();
        this.uri = uri;
        this.view = view;
    }
    eq(other) {
        return other.uri === this.uri;
    }
    toDOM() {
        const wrap = document.createElement("span");
        wrap.className = "cm-not-found-resource-widget";
        const guessName = this.uri.split("://")[1];
        wrap.textContent = `@${guessName ?? this.uri}`;
        return wrap;
    }
}
// Create decorations from resources
function createResourceDecorations(view) {
    const resources = view.state.field(resourcesField);
    const decorations = [];
    for (const { from, to } of view.visibleRanges) {
        const text = view.state.doc.sliceString(from, to);
        for (const match of matchAllURIs(text)) {
            const start = from + match.index;
            const uri = match[0].slice(1); // Remove @ prefix
            const resource = resources.get(uri);
            if (resource) {
                decorations.push(Decoration.replace({
                    widget: new ResourceWidget(resource, view),
                }).range(start, start + match[0].length));
            }
            else {
                decorations.push(Decoration.replace({
                    widget: new NotFoundResourceWidget(uri, view),
                }).range(start, start + match[0].length));
            }
        }
    }
    return Decoration.set(decorations);
}
// ViewPlugin for resource decorations
export const resourceDecorations = ViewPlugin.fromClass(class {
    decorations;
    constructor(view) {
        this.decorations = createResourceDecorations(view);
    }
    update(update) {
        if (update.docChanged ||
            update.viewportChanged ||
            update.transactions.some((tr) => tr.effects.some((e) => e.is(updateResources)))) {
            this.decorations = createResourceDecorations(update.view);
        }
    }
}, {
    decorations: (v) => v.decorations,
});
//# sourceMappingURL=decoration.js.map