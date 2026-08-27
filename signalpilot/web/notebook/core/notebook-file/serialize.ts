/**
 * Client-side serializer for the SignalPilot notebook `.py` file format.
 *
 * Best-effort port of notebook-server's codegen
 * (signalpilot/_ast/codegen.py::generate_filecontents). Differences from the
 * Python serializer, all tolerated by the Python loader (verified by
 * signalpilot/_ast/test_load_ts_serialized.py in the notebook-server):
 *
 *  - Cell signatures carry no refs (`def _():`) and the trailing return is a
 *    bare `return`. The Python loader recompiles each cell body and derives
 *    refs/defs from the AST, so signatures and return tuples are cosmetic.
 *  - `__generated_with` is emitted with a placeholder version; the loader
 *    treats a wrong/missing version as a soft violation.
 *  - No blank line is inserted before `return` when a cell ends with an
 *    import/def/class (a ruff-formatting nicety in the Python codegen).
 */

import { parser } from "@lezer/python";

const INDENT = "    ";

/**
 * Placeholder for `__generated_with`. The authoritative value is stamped by
 * the Python side on its next save; the loader only warns on mismatch.
 */
const GENERATED_WITH_PLACEHOLDER = "0.1.0";

const SETUP_CELL_NAME = "setup";
const DEFAULT_CELL_NAME = "_";
const TOPLEVEL_CELL_PREFIX = "*";

const IDENTIFIER_RE = /^[A-Za-z_]\w*$/;

export interface SerializableCellConfig {
  hide_code?: boolean | null;
  disabled?: boolean | null;
  column?: number | null;
}

export interface SerializableCell {
  code: string;
  name: string;
  config: SerializableCellConfig;
}

/** textwrap.indent semantics: only lines with non-whitespace get the prefix. */
function indentText(text: string): string {
  return text
    .split("\n")
    .map((line) => (line.trim() === "" ? line : INDENT + line))
    .join("\n");
}

/**
 * Non-default config entries rendered as decorator kwargs, in the same
 * field order the Python CellConfig uses (column, disabled, hide_code).
 */
function configArgs(config: SerializableCellConfig): string[] {
  const args: string[] = [];
  if (typeof config.column === "number") {
    args.push(`column=${config.column}`);
  }
  if (config.disabled === true) {
    args.push("disabled=True");
  }
  if (config.hide_code === true) {
    args.push("hide_code=True");
  }
  return args;
}

function decorator(fn: string, config: SerializableCellConfig): string {
  const args = configArgs(config);
  if (args.length === 0) {
    return `@app.${fn}`;
  }
  return `@app.${fn}(${args.join(", ")})`;
}

function codeHasSyntaxError(code: string): boolean {
  const cursor = parser.parse(code).cursor();
  do {
    if (cursor.type.isError) {
      return true;
    }
  } while (cursor.next());
  return false;
}

/** Port of codegen.generate_unparsable_cell. */
function unparsableCell(cell: SerializableCell): string {
  const { code } = cell;
  let codeAsStr: string;
  if (code.includes('"""')) {
    const escaped = code.replaceAll("\\", "\\\\").replaceAll('"', '\\"');
    codeAsStr = `"""\n${escaped}\n"""`;
  } else {
    codeAsStr = `r"""\n${code}\n"""`;
  }
  const flags: string[] = configArgs(cell.config);
  if (cell.name && cell.name !== DEFAULT_CELL_NAME) {
    flags.push(`name="${cell.name}"`);
  }
  const lines = ["app._unparsable_cell("];
  if (flags.length > 0) {
    lines.push(indentText(`${codeAsStr},`), indentText(flags.join(", ")));
  } else {
    lines.push(indentText(codeAsStr));
  }
  lines.push(")");
  return lines.join("\n");
}

function functionCell(cell: SerializableCell): string {
  const name = IDENTIFIER_RE.test(cell.name) ? cell.name : DEFAULT_CELL_NAME;
  const parts = [decorator("cell", cell.config), `def ${name}():`];
  const body = cell.code.replace(/\n+$/, "");
  if (body.trim() !== "") {
    parts.push(indentText(body));
  }
  parts.push(`${INDENT}return`);
  return parts.join("\n");
}

function toplevelCell(cell: SerializableCell): string {
  const code = cell.code.trim();
  const fn = /^class[\s(]/.test(code) ? "class_definition" : "function";
  return `${decorator(fn, cell.config)}\n${code}`;
}

function setupSection(cell: SerializableCell): string {
  let block = cell.code.replace(/\n+$/, "");
  if (block.trim() === "") {
    return "";
  }
  const onlyComments = block
    .split("\n")
    .every((line) => line.trim() === "" || line.trim().startsWith("#"));
  if (onlyComments) {
    block += "\npass";
  }
  const setupLine =
    cell.config.hide_code === true
      ? "with app.setup(hide_code=True):"
      : "with app.setup:";
  return [setupLine, indentText(block), "\n"].join("\n");
}

function serializeCell(cell: SerializableCell): string {
  if (cell.name.startsWith(TOPLEVEL_CELL_PREFIX)) {
    const code = cell.code.trim();
    if (
      (/^(?:async\s+)?def[\s(]/.test(code) || /^class[\s(:]/.test(code)) &&
      !codeHasSyntaxError(code)
    ) {
      return toplevelCell(cell);
    }
    // Fall back to a plain cell wrapping the body.
    return functionCell({ ...cell, name: DEFAULT_CELL_NAME });
  }
  if (cell.code.trim() !== "" && codeHasSyntaxError(cell.code)) {
    return unparsableCell(cell);
  }
  return functionCell(cell);
}

/**
 * Serialize editor cells to SignalPilot notebook `.py` file contents.
 *
 * A cell named "setup" becomes the `with app.setup:` block; a cell whose
 * name starts with "*" is emitted as a top-level
 * `@app.function`/`@app.class_definition`; cells whose code does not parse
 * are emitted as `app._unparsable_cell(...)`; everything else becomes an
 * `@app.cell` function.
 */
export function serializeNotebookPy(
  cells: SerializableCell[],
  opts?: { header?: string },
): string {
  const remaining = [...cells];
  const setupIndex = remaining.findIndex((c) => c.name === SETUP_CELL_NAME);
  let setup = "";
  if (setupIndex !== -1) {
    const [setupCell] = remaining.splice(setupIndex, 1);
    setup = setupSection(setupCell);
  }

  const cellBlocks = remaining.map(serializeCell).join("\n\n\n");

  const parts: string[] = [];
  if (opts?.header) {
    parts.push(opts.header.replace(/\s+$/, ""), "");
  }
  parts.push(
    "import signalpilot as sp",
    "",
    `__generated_with = "${GENERATED_WITH_PLACEHOLDER}"`,
    "app = sp.App()",
    "",
    setup,
    cellBlocks,
    "\n",
    'if __name__ == "__main__":',
    `${INDENT}app.run()`,
    "",
  );
  return parts.join("\n").replace(/^\s+/, "");
}

/** Canonical contents for a brand-new notebook: one empty anonymous cell. */
export function emptyNotebookPy(): string {
  return serializeNotebookPy([
    { code: "", name: DEFAULT_CELL_NAME, config: {} },
  ]);
}
