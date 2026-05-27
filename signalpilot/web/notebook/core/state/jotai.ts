import { dequal as isEqual } from "dequal";
import type { createStore} from "jotai";
import { type Atom, atom, useStore } from "jotai";
import { useEffect } from "react";
import { getCurrentStore } from "./store-binding";

export type JotaiStore = ReturnType<typeof createStore>;

/**
 * Module-level store proxy. Delegates get/set/sub to whichever store is
 * currently bound via bindStore() in store-binding.ts.
 *
 * Standalone app: mount() binds the module singleton before rendering.
 * Embed: SpEmbedProviders binds client.store for the lifetime of the tree.
 *
 * Identity is stable — referential equality checks keep working.
 */
export const store = {
  get: (<T>(a: Atom<T>) => getCurrentStore().get(a)) as JotaiStore["get"],
  set: ((...args) => (getCurrentStore().set as (...a: unknown[]) => void)(...args)) as JotaiStore["set"],
  sub: (<T>(a: Atom<T>, cb: () => void) => getCurrentStore().sub(a, cb)) as JotaiStore["sub"],
} as unknown as JotaiStore;

/**
 * Wait for an atom to satisfy a predicate.
 */
export async function waitFor<T>(
  atom: Atom<T>,
  predicate: (value: T) => boolean,
) {
  if (predicate(store.get(atom))) {
    return store.get(atom);
  }

  return new Promise<T>((resolve) => {
    const unsubscribe = store.sub(atom, () => {
      const value = store.get(atom);
      if (predicate(value)) {
        unsubscribe();
        resolve(value);
      }
    });
  });
}

/**
 * Create a Jotai effect that runs when an atom changes.
 */
export function useJotaiEffect<T>(
  atom: Atom<T>,
  effect: (value: T, prevValue: T) => void,
) {
  const store = useStore();
  useEffect(() => {
    let prevValue = store.get(atom);
    store.sub(atom, () => {
      const value = store.get(atom);
      effect(value, prevValue);
      prevValue = value;
    });
  }, [atom, effect, store]);
}

const sentinel = Symbol("sentinel");

export function createDeepEqualAtom<T>(
  baseAtom: Atom<T>,
  areEqual: (a: T, b: T) => boolean = isEqual,
) {
  let cachedValue: T | typeof sentinel = sentinel;

  return atom((get) => {
    const nextValue = get(baseAtom);

    if (cachedValue === sentinel || !areEqual(cachedValue, nextValue)) {
      cachedValue = nextValue;
    }

    return cachedValue;
  });
}
