import { EditorView } from "@codemirror/view";
import { tags as t } from "@lezer/highlight";
import { createTheme } from "thememirror";

export const darkTheme = [
  createTheme({
    variant: "dark",
    settings: {
      background: "#0a0a0a",
      foreground: "#eeeeee",
      caret: "#00ff88",
      selection: "rgba(0, 255, 136, 0.12)",
      lineHighlight: "rgba(255, 255, 255, 0.03)",
      gutterBackground: "#050505",
      gutterForeground: "#666666",
    },
    styles: [
      { tag: t.comment, color: "#666666" },
      { tag: t.variableName, color: "#eeeeee" },
      { tag: [t.string, t.special(t.brace)], color: "#00ff88" },
      { tag: t.number, color: "#ffaa00" },
      { tag: t.bool, color: "#ffaa00" },
      { tag: t.null, color: "#666666" },
      { tag: t.keyword, color: "#c678dd", fontWeight: 500 },
      { tag: t.className, color: "#60a5fa" },
      { tag: t.definition(t.typeName), color: "#60a5fa" },
      { tag: t.typeName, color: "#56b6c2" },
      { tag: t.angleBracket, color: "#999999" },
      { tag: t.tagName, color: "#ff4444" },
      { tag: t.attributeName, color: "#ffaa00" },
      { tag: t.operator, color: "#56b6c2", fontWeight: 500 },
      { tag: [t.function(t.variableName)], color: "#60a5fa" },
      { tag: [t.propertyName], color: "#e5c07b" },
    ],
  }),
  EditorView.theme({
    "&": {
      fontSize: "var(--sp-code-editor-font-size, 14px)",
      fontFamily:
        '"JetBrains Mono", "SF Mono", "Fira Code", "Cascadia Code", ui-monospace, monospace',
    },
    ".cm-gutters": {
      borderRight: "1px solid #222222",
    },
    ".cm-activeLineGutter": {
      background: "rgba(255, 255, 255, 0.04)",
    },
    ".cm-activeLine": {
      background: "rgba(255, 255, 255, 0.03)",
    },
    ".cm-selectionMatch": {
      background: "rgba(0, 255, 136, 0.08)",
    },
    ".cm-cursor": {
      borderLeftColor: "#00ff88",
    },
    ".cm-matchingBracket": {
      background: "rgba(0, 255, 136, 0.15)",
      outline: "1px solid rgba(0, 255, 136, 0.3)",
    },
    ".cm-foldGutter": {
      color: "#444444",
    },
    ".cm-foldGutter:hover": {
      color: "#999999",
    },
    ".cm-searchMatch": {
      background: "rgba(255, 170, 0, 0.2)",
      outline: "1px solid rgba(255, 170, 0, 0.4)",
    },
    ".cm-searchMatch.cm-searchMatch-selected": {
      background: "rgba(255, 170, 0, 0.35)",
    },
  }),
];
