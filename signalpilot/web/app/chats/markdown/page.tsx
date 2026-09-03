import { MarkdownShowcase } from "~/components/chat/markdown-showcase";

export const metadata = { title: "Chat markdown playground" };

/**
 * Every component the chat markdown renderer supports, editable side by side
 * with its rendered output. Use it to check a widget before teaching the agent
 * to write it.
 */
export default function ChatMarkdownPage() {
  return (
    <div className="h-screen overflow-hidden p-4">
      <div className="flex h-full flex-col overflow-hidden rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg)] shadow-2xl shadow-black/20">
        <MarkdownShowcase />
      </div>
    </div>
  );
}
