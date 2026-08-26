import { Facet } from "@codemirror/state";
export function createUseLastOrThrow(message) {
    const fallback = new Proxy({}, {
        get() {
            throw new Error(message);
        },
    });
    return function useLastOrThrow(values) {
        return values.at(-1) ?? fallback;
    };
}
export const documentUri = Facet.define({
    combine: createUseLastOrThrow("No document URI provided. Either pass a one into the extension or use documentUri.of()."),
});
export const languageId = Facet.define({
    combine: createUseLastOrThrow("No language ID provided. Either pass a one into the extension or use languageId.of()."),
});
//# sourceMappingURL=config.js.map