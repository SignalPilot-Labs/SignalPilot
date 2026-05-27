/**
 * Whether the current environment is in the VSCode extension
 */
export function isInVscodeExtension(): boolean {
  // Guard for SSR / environments without DOM (e.g. Next.js server rendering)
  if (typeof document === "undefined") return false;
  // We check if the document has a data-vscode-theme-kind attribute
  return document.querySelector("[data-vscode-theme-kind]") !== null;
}
