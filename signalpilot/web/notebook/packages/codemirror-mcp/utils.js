export const URI_PATTERN = /@[\w-]+:\/\/(?!\/)[^\s]+/;
export function matchAllURIs(text) {
    return text.matchAll(new RegExp(URI_PATTERN.source, "g"));
}
export function invariant(condition, message) {
    if (!condition) {
        throw new Error(message);
    }
}
//# sourceMappingURL=utils.js.map