import { EditorView } from "@codemirror/view";
// Theme for resource decorations
export const resourceTheme = EditorView.baseTheme({
    ".cm-resource-widget": {
        background: "light-dark(rgba(86,156,214,0.08),rgba(86,156,214,0.18))",
        borderRadius: "4px",
        padding: "2px 4px",
        color: "light-dark(#2367a2,#7ecbff)",
        fontWeight: "500",
    },
    ".cm-resource-widget:hover": {
        background: "light-dark(rgba(86,156,214,0.18),rgba(86,156,214,0.28))",
    },
    ".cm-not-found-resource-widget": {
        background: "light-dark(rgba(151,151,151,0.08),rgba(151,151,151,0.18))",
        borderRadius: "4px",
        padding: "2px 4px",
        color: "light-dark(#b00020,#ff8080)",
        fontWeight: "500",
    },
});
//# sourceMappingURL=theme.js.map