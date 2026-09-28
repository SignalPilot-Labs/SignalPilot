import { act } from "react";

/** Click a tool row open: rows mount collapsed and open only on a click. */
export async function openToolRow(root: ParentNode, index = 0): Promise<void> {
  const rows = root.querySelectorAll<HTMLButtonElement>('[data-testid="chat-tool-chip"]');
  const row = rows[index];
  if (!row) throw new Error("no tool row to open");
  await act(async () => row.click());
}
