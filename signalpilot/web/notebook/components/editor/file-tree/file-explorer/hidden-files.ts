import { atomWithStorage } from "jotai/utils";
import type { FileInfo } from "@/core/network/types";
import { jotaiJsonStorage } from "@/utils/storage/jotai";

export const hiddenFilesState = atomWithStorage(
  "sp:showHiddenFiles",
  true,
  jotaiJsonStorage,
  {
    getOnInit: true,
  },
);

export function filterHiddenTree(
  list: FileInfo[],
  showHidden: boolean,
): FileInfo[] {
  if (showHidden) {
    return list;
  }

  const out: FileInfo[] = [];
  for (const item of list) {
    if (isDirectoryOrFileHidden(item.name)) {
      continue;
    }
    let next = item;
    if (item.children) {
      const kids = filterHiddenTree(item.children, showHidden);
      if (kids !== item.children) {
        next = { ...item, children: kids };
      }
    }
    out.push(next);
  }
  return out;
}

export function isDirectoryOrFileHidden(filename: string): boolean {
  if (filename.startsWith(".")) {
    return true;
  }
  return false;
}
