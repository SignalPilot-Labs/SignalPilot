import { invariant } from "@/utils/invariant";
import type { ModelLifecycle } from "../kernel/messages";
import type { SpStaticState, StaticVirtualFiles } from "./types";

declare global {
  interface Window {
    __SP_STATIC__?: Readonly<SpStaticState>;
  }
}

function isStringToStringRecord(
  value: unknown,
): value is Record<string, string> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return false;
  }
  for (const entry of Object.values(value)) {
    if (typeof entry !== "string") {
      return false;
    }
  }
  return true;
}

function isSpStaticState(
  value: unknown,
): value is Readonly<SpStaticState> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return false;
  }
  const candidate = value as SpStaticState;
  if (!isStringToStringRecord(candidate.files)) {
    return false;
  }
  if (
    candidate.modelNotifications !== undefined &&
    !Array.isArray(candidate.modelNotifications)
  ) {
    return false;
  }
  return true;
}

function getSpStaticState(): Readonly<SpStaticState> | undefined {
  // `typeof window` guard handles the identifier-undeclared case (e.g.
  // leaked async work firing after jsdom teardown in tests); `?.` only
  // short-circuits on null/undefined.
  const state =
    typeof window === "undefined" ? undefined : window.__SP_STATIC__;
  return isSpStaticState(state) ? state : undefined;
}

export function isStaticNotebook(): boolean {
  return getSpStaticState() !== undefined;
}

export function getStaticVirtualFiles(): StaticVirtualFiles {
  const state = getSpStaticState();
  invariant(state !== undefined, "Not a static notebook");
  return state.files;
}

export function getStaticModelNotifications(): ModelLifecycle[] | undefined {
  return getSpStaticState()?.modelNotifications;
}
