import type { DataURLString } from "@/utils/json/base64";
import type { ModelLifecycle } from "../kernel/messages";

export type StaticVirtualFiles = Record<string, DataURLString>;

export interface SpStaticState {
  files: StaticVirtualFiles;
  modelNotifications?: ModelLifecycle[];
}
