# Copyright 2026 SignalPilot. All rights reserved.
from __future__ import annotations

from signalpilot._schemas.notebook import NotebookV1
from signalpilot._schemas.serialization import (
    EMPTY_NOTEBOOK_SERIALIZATION,
    NotebookSerialization,
)


class SpConverterIntermediate:
    """Intermediate representation that allows chaining conversions."""

    def __init__(self, ir: NotebookSerialization):
        self.ir = ir

    def to_notebook_v1(self) -> NotebookV1:
        """Convert to NotebookV1 format."""
        from signalpilot._convert.notebook import convert_from_ir_to_notebook_v1

        return convert_from_ir_to_notebook_v1(self.ir)

    def to_markdown(self, filename: str | None = None) -> str:
        """Convert to markdown format."""
        from signalpilot._convert.markdown import convert_from_ir_to_markdown

        return convert_from_ir_to_markdown(self.ir, filename)

    def to_py(self) -> str:
        """Convert to python format."""
        from signalpilot._ast.codegen import generate_filecontents_from_ir

        return generate_filecontents_from_ir(self.ir)

    def to_ir(self) -> NotebookSerialization:
        """Convert to notebook IR."""
        return self.ir


class SpConvert:
    """Converter utility for sp notebooks."""

    @staticmethod
    def from_py(source: str) -> SpConverterIntermediate:
        """Convert from sp Python source code.

        Args:
            source: Python source code string
        """
        from signalpilot._ast.parse import parse_notebook

        ir = parse_notebook(source) or EMPTY_NOTEBOOK_SERIALIZATION
        return SpConverterIntermediate(ir)

    @staticmethod
    def from_non_signalpilot_python_script(
        source: str,
        aggressive: bool = False,
    ) -> SpConverterIntermediate:
        """Convert from a non-sp Python script to sp notebook.

        This should only be used when the .py file is not already a valid
        sp notebook.

        Args:
            source: Unknown Python script source code string
            aggressive: If True, will attempt to convert aggressively,
                        turning even invalid text into a notebook.
        """
        from signalpilot._convert.non_signalpilot_python_script import (
            convert_non_signalpilot_python_script_to_notebook_ir,
            convert_non_signalpilot_script_to_notebook_ir,
        )

        if aggressive:
            notebook_ir = convert_non_signalpilot_script_to_notebook_ir(source)
        else:
            notebook_ir = convert_non_signalpilot_python_script_to_notebook_ir(
                source
            )
        return SpConvert.from_ir(notebook_ir)

    @staticmethod
    def from_plain_text(
        source: str,
    ) -> SpConverterIntermediate:
        """Converts plain text into a single celled sp notebook.

        Used for cases with syntax errors or unparsable code.

        Args:
            source: Unknown source code string
        """
        from signalpilot._convert.non_signalpilot_python_script import (
            convert_script_block_to_notebook_ir,
        )

        return SpConvert.from_ir(
            convert_script_block_to_notebook_ir(source)
        )

    @staticmethod
    def from_md(source: str) -> SpConverterIntermediate:
        """Convert from markdown source code.

        Args:
            source: Markdown source code string
        """
        from signalpilot._convert.markdown.to_ir import (
            convert_from_md_to_signalpilot_ir,
        )

        return SpConvert.from_ir(convert_from_md_to_signalpilot_ir(source))

    @staticmethod
    def from_ipynb(source: str) -> SpConverterIntermediate:
        """Convert from Jupyter notebook JSON.

        Args:
            source: Jupyter notebook JSON string
        """
        from signalpilot._convert.ipynb.to_ir import (
            convert_from_ipynb_to_notebook_ir,
        )

        return SpConvert.from_ir(convert_from_ipynb_to_notebook_ir(source))

    @staticmethod
    def from_notebook_v1(
        notebook_v1: NotebookV1,
    ) -> SpConverterIntermediate:
        """Convert from notebook v1.

        Args:
            notebook_v1: Notebook v1
        """
        from signalpilot._convert.notebook import convert_from_notebook_v1_to_ir

        return SpConverterIntermediate(
            convert_from_notebook_v1_to_ir(notebook_v1)
        )

    @staticmethod
    def from_ir(ir: NotebookSerialization) -> SpConverterIntermediate:
        """Convert from notebook IR.

        Args:
            ir: Notebook IR
        """
        return SpConverterIntermediate(ir)
