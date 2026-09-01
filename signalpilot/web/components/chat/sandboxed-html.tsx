"use client";

/**
 * Sandboxed iframe for agent-produced HTML. Scripts stay off by default;
 * the frame is never same-origin and never sends a referrer.
 */
export function SandboxedHtml({
  html,
  allowScripts = false,
  className = "h-[440px] w-full border-0 bg-white",
  title = "Sandboxed HTML",
}: {
  html: string;
  allowScripts?: boolean;
  className?: string;
  title?: string;
}) {
  return (
    <iframe
      title={title}
      sandbox={allowScripts ? "allow-scripts" : ""}
      referrerPolicy="no-referrer"
      srcDoc={html}
      className={className}
    />
  );
}
