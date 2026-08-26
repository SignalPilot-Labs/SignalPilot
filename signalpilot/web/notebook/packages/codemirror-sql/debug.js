export function debug(message, ...args) {
    // @ts-expect-error - import.meta.env is not typed
    if (import.meta.env.DEV) {
        console.log(`[codemirror-sql]`, message, ...args);
    }
}
//# sourceMappingURL=debug.js.map