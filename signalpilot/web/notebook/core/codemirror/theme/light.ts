import { EditorView } from "@codemirror/view";
import { tags as t } from "@lezer/highlight";
import { createTheme } from "thememirror";

export const lightTheme = [
  createTheme({
    variant: "light",
    settings: {
      background: "#ffffff",
      foreground: "#000000",
      caret: "#000000",
      selection: "#d7d4f0",
      lineHighlight: "#cceeff44",
      gutterBackground: "var(--color-background)",
      gutterForeground: "var(--gray-10)",
    },
    styles: [
      { tag: t.comment, color: "var(--cm-comment)" },
      { tag: t.variableName, color: "#000000" },
      { tag: [t.string, t.special(t.brace)], color: "#a11" },
      { tag: t.number, color: "#164" },
      { tag: t.bool, color: "#219" },
      { tag: t.null, color: "#219" },
      { tag: t.keyword, color: "#708", fontWeight: 500 },
      { tag: t.className, color: "#00f" },
      { tag: t.definition(t.typeName), color: "#00f" },
      { tag: t.typeName, color: "#085" },
      { tag: t.angleBracket, color: "#000000" },
      { tag: t.tagName, color: "#170" },
      { tag: t.attributeName, color: "#00c" },
      { tag: t.operator, color: "#a2f", fontWeight: 500 },
      { tag: [t.function(t.variableName)], color: "#00c" },
      { tag: [t.propertyName], color: "#05a" },
    ],
  }),
  EditorView.theme({
    "&": {
      fontSize: "var(--sp-code-editor-font-size, 14px)",
      fontFamily:
        '"JetBrains Mono", "SF Mono", "Fira Code", "Cascadia Code", ui-monospace, monospace',
    },
    ".mo-cm-reactive-reference": {
      fontWeight: "400",
      color: "#005f87",
      borderBottom: "2px solid #bad3de",
    },
    ".mo-cm-reactive-reference-hover": {
      cursor: "pointer",
      borderBottomWidth: "3px",
    },
  }),
];
