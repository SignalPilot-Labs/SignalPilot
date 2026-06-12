import { atom } from "jotai";
import type { OutputMessage } from "../kernel/messages";

interface DebuggerState {
  cellId: string;
  outputs: OutputMessage[];
}

export const debuggerAtom = atom<DebuggerState | undefined>(undefined);
