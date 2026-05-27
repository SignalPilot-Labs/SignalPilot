from __future__ import annotations

from pathlib import Path

import click

from signalpilot._cli.convert.utils import load_external_file
from signalpilot._cli.errors import SpCLIMissingDependencyError
from signalpilot._cli.print import echo
from signalpilot._cli.utils import prompt_to_overwrite
from signalpilot._convert.converters import SpConvert
from signalpilot._utils.paths import maybe_make_dirs


def _build_rerun_command(filename: str, output: Path | None) -> str:
    command = f"sp convert {filename}"
    if output is not None:
        command = f"{command} -o {output}"
    return command


@click.argument("filename", required=True)
@click.option(
    "-o",
    "--output",
    type=click.Path(path_type=Path),
    default=None,
    help=(
        "Output file to save the converted notebook to. "
        "If not provided, the converted notebook will be printed to stdout."
    ),
)
def convert(
    filename: str,
    output: Path | None,
) -> None:
    r"""Convert a Jupyter notebook, Markdown file, or Python script to a sp notebook.

    Supported input formats:
    - `.ipynb` (local or GitHub-hosted)
    - `.md` files with `{python}` code fences
    - `.py` scripts in py:percent format

    Behavior:
    - Jupyter notebooks: outputs are stripped.

    - Markdown files: only `{python}` fenced code blocks are converted.

    Example:
      ```{python}
      x = 1 + 2
      print(x)
      ```
    - Python scripts:
        - If already a valid sp notebook, no conversion is performed.
        - Otherwise, sp attempts to convert using py:percent formatting,
          preserving top-level comments and docstrings.

    Example usage:

        sp convert your_nb.ipynb -o your_nb.py

    or

        sp convert your_nb.md -o your_nb.py

    or

        sp convert script.py -o your_nb.py

    You can also pass global flags to the main sp command.
    For example, use `-q` to suppress output or `-y`
    to automatically accept all prompts of the command.

        sp -q -y convert script.py -o your_nb.py

    After conversion:

        sp edit your_nb.py

    Note:
    Since sp's reactive execution differs from traditional notebooks,
    you may need to refactor code that mutates variables across cells
    (e.g., modifying a dataframe in multiple cells), which can lead to
    unexpected behavior.
    """

    ext = Path(filename).suffix
    if ext not in (".ipynb", ".md", ".qmd", ".py"):
        raise click.UsageError("File must be an .ipynb, .md, or .py file")

    text = load_external_file(filename, ext)
    if ext == ".ipynb":
        notebook = SpConvert.from_ipynb(text).to_py()
    elif ext in (".md", ".qmd"):
        notebook = SpConvert.from_md(text).to_py()
    else:
        assert ext == ".py"
        # First check if it's already a valid sp notebook
        from signalpilot._ast.parse import parse_notebook

        try:
            parsed = parse_notebook(text)
        except SyntaxError:
            # File has syntax errors
            echo("File cannot be converted. It may have syntax errors.")
            return

        if parsed and parsed.valid:
            # Already a valid sp notebook
            echo("File is already a valid sp notebook.")
            return

        try:
            notebook = SpConvert.from_non_signalpilot_python_script(
                text
            ).to_py()
        except ImportError as e:
            # Check if jupytext is the missing module in the cause chain
            if (
                e.__cause__
                and getattr(e.__cause__, "name", None) == "jupytext"
            ):
                rerun_command = _build_rerun_command(filename, output)
                raise SpCLIMissingDependencyError(
                    str(e),
                    "jupytext",
                    followup_commands=rerun_command,
                    followup_label="Then rerun:",
                ) from e
            raise

    if output:
        output_path = output
        if prompt_to_overwrite(output_path):
            # Make dirs if needed
            maybe_make_dirs(output_path)
            output_path.write_text(notebook, encoding="utf-8")
            echo(f"Converted notebook saved to {output}")
    else:
        echo(notebook)
