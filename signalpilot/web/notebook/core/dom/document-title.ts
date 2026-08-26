import { getCurrentClient } from "@/embed/client-binding";

/**
 * Write document.title, unless an embed client has opted out.
 * Standalone path leaves the client stack empty — defaults to writing.
 */
export function setDocumentTitle(title: string): void {
  const client = getCurrentClient();
  if (client !== undefined && !client.options.writeDocumentTitle) {
    return;
  }
  document.title = title;
}
