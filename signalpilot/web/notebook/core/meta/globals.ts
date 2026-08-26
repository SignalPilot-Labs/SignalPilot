import { spVersionAtom, serverTokenAtom } from "@/core/meta/state";
import { store } from "@/core/state/jotai";

/**
 * This should be avoided and instead use the store.
 */
export const getSpVersion = () => store.get(spVersionAtom);
/**
 * This should be avoided and instead use the store.
 */
export const getSpServerToken = () => store.get(serverTokenAtom);

/**
 * N.B This still exists for backwards compatibility.
 * Some code paths still look for the sp-code html tag.
 */
export const getSpCode = (): string | undefined => {
  const tag = document.querySelector("sp-code");
  if (!tag) {
    return undefined;
  }
  const inner = tag.innerHTML;
  return decodeURIComponent(inner).trim();
};
