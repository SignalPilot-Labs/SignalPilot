import { atomWithStorage } from "jotai/utils";
import { jotaiJsonStorage } from "@/utils/storage/jotai";
// Default: true (Enter accepts suggestion, matching VS Code default)
export const acceptCompletionOnEnterAtom = atomWithStorage<boolean>(
  "sp:accept-completion-on-enter",
  true,
  jotaiJsonStorage,
  { getOnInit: true },
);
