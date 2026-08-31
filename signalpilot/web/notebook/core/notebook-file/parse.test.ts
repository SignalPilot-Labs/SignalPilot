/**
 * Tests for the client-side notebook .py parser/serializer.
 *
 * Fixture .py files under __fixtures__/ were generated with the REAL Python
 * serializer (signalpilot/_ast/codegen.py::generate_filecontents) and each
 * .expected.json is the NotebookV1 produced by the REAL
 * signalpilot/_session/state/serialize.py::serialize_notebook for that file.
 * Regenerate with the script noted in __fixtures__/README-less spirit:
 * generate fixtures from notebook-server via generate_filecontents +
 * serialize_notebook (see PR description / test history).
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { parseNotebookPy } from "./parse";
import { emptyNotebookPy, serializeNotebookPy } from "./serialize";
import type { SerializableCell } from "./serialize";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FIXTURES_DIR = path.join(HERE, "__fixtures__");

interface ExpectedCell {
  code: string;
  code_hash: string | null;
  config: {
    column: number | null;
    disabled: boolean | null;
    hide_code: boolean | null;
  };
  id: string;
  name: string;
}

interface ExpectedNotebook {
  cells: ExpectedCell[];
  metadata: { signalpilot_version?: string | null };
  version: string;
}

const fixtureNames = fs
  .readdirSync(FIXTURES_DIR)
  .filter((f) => f.endsWith(".py"))
  .map((f) => f.replace(/\.py$/, ""))
  .sort();

function loadFixture(name: string): { py: string; expected: ExpectedNotebook } {
  const py = fs.readFileSync(path.join(FIXTURES_DIR, `${name}.py`), "utf8");
  const expected = JSON.parse(
    fs.readFileSync(path.join(FIXTURES_DIR, `${name}.expected.json`), "utf8"),
  ) as ExpectedNotebook;
  return { py, expected };
}

/** Strip the (random) id so cells can be deep-compared. */
function comparable(cells: Array<Omit<ExpectedCell, "id"> & { id?: unknown }>) {
  return cells.map(({ code, code_hash, config, name }) => ({
    code,
    code_hash,
    config: {
      column: config.column ?? null,
      disabled: config.disabled ?? false,
      hide_code: config.hide_code ?? false,
    },
    name,
  }));
}

describe("parseNotebookPy", () => {
  it("has fixtures to test against", () => {
    expect(fixtureNames.length).toBeGreaterThan(5);
  });

  for (const name of fixtureNames) {
    it(`parses fixture ${name} to the Python-serialized NotebookV1`, () => {
      const { py, expected } = loadFixture(name);
      const result = parseNotebookPy(py);
      expect(result).not.toBeNull();
      const notebook = result!.notebook;

      expect(notebook.version).toBe("1");
      expect(notebook.metadata.sp_version).toBe(
        expected.metadata.signalpilot_version,
      );
      expect(comparable(notebook.cells as ExpectedCell[])).toEqual(
        comparable(expected.cells),
      );

      // Setup cell keeps its well-known id; other ids are fresh and unique.
      const ids = notebook.cells.map((c) => c.id);
      expect(new Set(ids).size).toBe(ids.length);
      for (const cell of notebook.cells) {
        if (cell.name === "setup") {
          expect(cell.id).toBe("setup");
        } else {
          expect(cell.id).toMatch(/^[A-Za-z]{4}$/);
        }
      }
    });

    it(`round-trips fixture ${name} through serializeNotebookPy`, () => {
      const { py, expected } = loadFixture(name);
      const parsed = parseNotebookPy(py)!.notebook;
      const reserialized = serializeNotebookPy(
        parsed.cells.map((c) => ({
          code: c.code ?? "",
          name: c.name ?? "_",
          config: c.config,
        })) as SerializableCell[],
      );
      const reparsed = parseNotebookPy(reserialized);
      expect(reparsed).not.toBeNull();
      expect(comparable(reparsed!.notebook.cells as ExpectedCell[])).toEqual(
        comparable(expected.cells),
      );
    });
  }

  it("returns null for non-notebook Python", () => {
    expect(parseNotebookPy("x = 1\nprint(x)\n")).toBeNull();
    expect(parseNotebookPy("import os\n\nos.getcwd()\n")).toBeNull();
  });

  it("returns null for empty and garbage input", () => {
    expect(parseNotebookPy("")).toBeNull();
    expect(parseNotebookPy("   \n\n  ")).toBeNull();
    expect(parseNotebookPy("this is not ( valid python")).toBeNull();
  });

  it("returns null when a notebook file has a syntax error", () => {
    const { py } = loadFixture("basic");
    expect(parseNotebookPy(py + "\ndef broken(:\n")).toBeNull();
  });

  it("tolerates a missing __generated_with (soft violation)", () => {
    const py = [
      "import signalpilot as sp",
      "",
      "app = sp.App()",
      "",
      "",
      "@app.cell",
      "def _():",
      "    x = 1",
      "    return",
      "",
      "",
      'if __name__ == "__main__":',
      "    app.run()",
      "",
    ].join("\n");
    const result = parseNotebookPy(py);
    expect(result).not.toBeNull();
    expect(result!.notebook.cells).toHaveLength(1);
    expect(result!.notebook.cells[0].code).toBe("x = 1");
    expect(result!.notebook.metadata.sp_version).toBeNull();
  });
});

describe("serializeNotebookPy", () => {
  it("emptyNotebookPy parses to a single empty anonymous cell", () => {
    const result = parseNotebookPy(emptyNotebookPy());
    expect(result).not.toBeNull();
    const { cells } = result!.notebook;
    expect(cells).toHaveLength(1);
    expect(cells[0].code).toBe("");
    expect(cells[0].code_hash).toBeNull();
    expect(cells[0].name).toBe("_");
  });

  it("emits the notebook skeleton", () => {
    const out = serializeNotebookPy([
      { code: "x = 1", name: "_", config: {} },
      { code: "y = x + 1", name: "second", config: { hide_code: true } },
    ]);
    expect(out.startsWith("import signalpilot as sp\n")).toBe(true);
    expect(out).toContain("app = sp.App()");
    expect(out).toContain("@app.cell\ndef _():\n    x = 1\n    return");
    expect(out).toContain(
      "@app.cell(hide_code=True)\ndef second():\n    y = x + 1\n    return",
    );
    expect(out.trimEnd().endsWith('if __name__ == "__main__":\n    app.run()')).toBe(
      true,
    );
  });

  it("emits a setup block for the cell named setup", () => {
    const out = serializeNotebookPy([
      { code: "import os", name: "setup", config: {} },
      { code: "print(os.sep)", name: "_", config: {} },
    ]);
    expect(out).toContain("with app.setup:\n    import os");
    const reparsed = parseNotebookPy(out)!.notebook;
    expect(reparsed.cells[0].name).toBe("setup");
    expect(reparsed.cells[0].code).toBe("import os");
  });

  it("emits unparsable cells for code with syntax errors", () => {
    const out = serializeNotebookPy([
      { code: "x = 1", name: "_", config: {} },
      { code: "not ( valid", name: "broken", config: {} },
    ]);
    expect(out).toContain("app._unparsable_cell(");
    const reparsed = parseNotebookPy(out)!.notebook;
    expect(reparsed.cells[1].code).toBe("not ( valid");
    expect(reparsed.cells[1].name).toBe("broken");
  });

  it("invalid cell names fall back to an anonymous def", () => {
    const out = serializeNotebookPy([
      { code: "x = 1", name: "not a name", config: {} },
    ]);
    expect(out).toContain("def _():");
  });
});
