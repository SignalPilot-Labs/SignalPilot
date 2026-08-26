/**
 * Lazy evaluation of a function that returns a promise.
 */
export const lazy = (fn) => {
    let value;
    return async () => {
        if (!value) {
            value = fn();
        }
        return await value;
    };
};
//# sourceMappingURL=utils.js.map