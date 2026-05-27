import { type Extension } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import type { SqlParser } from "./types.js";
export interface SqlGutterConfig {
    /** Background color for the current statement indicator */
    backgroundColor?: string;
    /** Background color for invalid statements */
    errorBackgroundColor?: string;
    /** Width of the gutter marker in pixels */
    width?: number;
    /** Additional CSS class for the gutter */
    className?: string;
    /** Whether to show markers for invalid statements */
    showInvalid?: boolean;
    /** Function to determine when to hide the gutter */
    whenHide?: (view: EditorView) => boolean;
    /** Opacity for non-current statements */
    inactiveOpacity?: number;
    /** Hide gutter when editor is not focused */
    hideWhenNotFocused?: boolean;
    /** Opacity when editor is not focused (overrides hideWhenNotFocused if set) */
    unfocusedOpacity?: number;
    /** Custom SQL parser instance to use for analysis */
    parser?: SqlParser;
}
/**
 * Creates a SQL gutter extension that shows visual indicators for SQL statements
 * based on cursor position. Highlights the current statement and shows dimmed
 * indicators for other statements.
 */
export declare function sqlStructureGutter(config?: SqlGutterConfig): Extension[];
//# sourceMappingURL=structure-extension.d.ts.map