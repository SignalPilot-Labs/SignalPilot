/**
 * Render a minimal boot error UI into the given root element.
 *
 * Pure DOM — no React. React is not booted when mount-config fetch fails,
 * so this must not import any React/JSX.
 *
 * Matches the app's dark theme (background #050505, foreground #e0e0e0).
 */
export function renderBootError(root: HTMLElement, err: unknown): void {
  const message =
    err instanceof Error ? err.message : "An unexpected error occurred.";

  root.style.cssText =
    "display:flex;align-items:center;justify-content:center;min-height:100vh;background:#050505;color:#e0e0e0;font-family:system-ui,sans-serif;";

  const box = document.createElement("div");
  box.style.cssText =
    "max-width:480px;padding:2rem;border:1px solid #2a2a2a;border-radius:8px;background:#0d0d0d;";

  const heading = document.createElement("h2");
  heading.style.cssText =
    "margin:0 0 0.75rem;font-size:1.25rem;font-weight:600;color:#ff6b6b;";
  heading.textContent = "Failed to start";

  const body = document.createElement("p");
  body.style.cssText = "margin:0 0 1.5rem;font-size:0.875rem;line-height:1.6;color:#a0a0a0;word-break:break-word;";
  body.textContent = message;

  const reloadBtn = document.createElement("button");
  reloadBtn.style.cssText =
    "padding:0.5rem 1.25rem;background:#1a1a1a;color:#e0e0e0;border:1px solid #333;border-radius:4px;font-size:0.875rem;cursor:pointer;";
  reloadBtn.textContent = "Reload";
  reloadBtn.addEventListener("click", () => {
    window.location.reload();
  });

  box.append(heading, body, reloadBtn);
  root.replaceChildren(box);
}
