import type { OutputMessage } from "./kernel/messages";

export function isErrorMime(mime: OutputMessage["mimetype"] | undefined) {
  return (
    mime === "application/vnd.sp+error" ||
    mime === "application/vnd.sp+traceback"
  );
}
