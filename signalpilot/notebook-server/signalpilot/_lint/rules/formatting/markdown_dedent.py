from __future__ import annotations

from typing import TYPE_CHECKING

from signalpilot._ast.codegen import format_markdown
from signalpilot._lint.diagnostic import Diagnostic, Severity
from signalpilot._lint.rules.base import LintRule

if TYPE_CHECKING:
    from signalpilot._lint.context import RuleContext


class MarkdownDedentRule(LintRule):
    """MF007: Markdown strings in `sp.md()` should be properly indented.

    This rule detects markdown strings in `sp.md()` calls that have unnecessary
    leading indentation. Proper markdown indentation improves readability and produces
    cleaner diffs in version control.

    ## What it does

    Checks cells containing `sp.md()` calls to see if the markdown string
    content has unnecessary leading whitespace that should be removed.

    ## Why is this bad?

    Indented markdown strings:
    - Are harder to read when viewing the source code
    - Produce larger diffs when making changes
    - Don't match the standard sp formatting style
    - Can be confusing when the indentation doesn't reflect the markdown structure

    ## Examples

    **Problematic:**
    ```python
    sp.md(
        r\"\"\"
        # Title

        Some content here.
        \"\"\"
    )
    ```

    **Solution:**
    ```python
    sp.md(r\"\"\"
    # Title

    Some content here.
    \"\"\")
    ```

    **Note:** This fix is automatically applied with `sp check --fix`.

    ## References

    - [Understanding Errors](https://docs.signalpilot.ai/docs/)
    - [Best Practices](https://docs.signalpilot.ai/docs/)
    """

    code = "MF007"
    name = "markdown-indentation"
    description = "Markdown cells in `sp.md()` should be properly indented."
    severity = Severity.FORMATTING
    fixable = True

    async def check(self, ctx: RuleContext) -> None:
        """Check for markdown cells with indented content."""
        from signalpilot._lint.linter import (
            contents_differ_excluding_generated_with,
        )

        graph = ctx.get_graph()

        # Check each cell in the graph
        for cell in graph.cells.values():
            # Only check markdown cells
            if cell.markdown is None:
                continue

            notebook_cell = None
            for nb_cell in ctx.notebook.cells:
                if nb_cell.code.strip() == cell.code.strip():
                    notebook_cell = nb_cell
                    break

            if not notebook_cell:
                continue

            # Check if the markdown string needs dedenting
            # Use tokenize like codegen does to extract quote style
            needs_dedent = contents_differ_excluding_generated_with(
                format_markdown(cell), cell.code
            )

            # Only applicable in python context
            overly_dedented = False
            if ctx.notebook.filename and ctx.notebook.filename.endswith(".py"):
                line_count = len(cell.code.splitlines())
                line_start = notebook_cell.lineno + 1
                overly_dedented = any(
                    line[0] != " "
                    for line in ctx.contents[
                        line_start : line_start + line_count
                    ]
                    if line
                )

            if needs_dedent or overly_dedented:
                # Find the corresponding notebook cell for position info
                notebook_cell = None
                for nb_cell in ctx.notebook.cells:
                    if nb_cell.code.strip() == cell.code.strip():
                        notebook_cell = nb_cell
                        break

                if notebook_cell:
                    diagnostic = Diagnostic(
                        message="Markdown cell should be dedented for better readability",
                        line=notebook_cell.lineno - 1,
                        column=notebook_cell.col_offset + 1,
                    )
                    await ctx.add_diagnostic(diagnostic)
