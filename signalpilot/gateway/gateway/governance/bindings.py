"""Typed, value-free SQL binding contracts for governed execution."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ParameterStyle(StrEnum):
    FORMAT = "format"
    NUMERIC_DOLLAR = "numeric_dollar"
    QMARK = "qmark"
    NAMED_PYFORMAT = "named_pyformat"


_TOKEN_PREFIX = ":sp_dashboard_"
_TOKEN_RE = re.compile(r":sp_dashboard_(\d+)\b")


class BoundQueryError(ValueError):
    pass


@dataclass(frozen=True)
class RenderedBoundQuery:
    sql: str
    parameters: list[Any] | dict[str, Any]


def parameter_token(index: int) -> str:
    if index < 0:
        raise BoundQueryError("Parameter indexes must be non-negative")
    return f"{_TOKEN_PREFIX}{index}"


def _replace_outside_sql_literals(sql: str, replacer) -> tuple[str, list[int]]:
    """Replace internal tokens while preserving quoted text and comments."""
    output: list[str] = []
    indexes: list[int] = []
    index = 0
    state = "normal"
    while index < len(sql):
        char = sql[index]
        following = sql[index + 1] if index + 1 < len(sql) else ""
        if state == "normal":
            if char == "'":
                state = "single"
            elif char == '"':
                state = "double"
            elif char == "[":
                state = "bracket"
            elif char == "`":
                state = "backtick"
            elif char == "-" and following == "-":
                state = "line_comment"
            elif char == "/" and following == "*":
                state = "block_comment"
            elif sql.startswith(_TOKEN_PREFIX, index):
                match = _TOKEN_RE.match(sql, index)
                if match is not None:
                    parameter_index = int(match.group(1))
                    output.append(replacer(parameter_index))
                    indexes.append(parameter_index)
                    index = match.end()
                    continue
        elif state == "single" and char == "'":
            if following == "'":
                output.extend((char, following))
                index += 2
                continue
            state = "normal"
        elif state == "double" and char == '"':
            if following == '"':
                output.extend((char, following))
                index += 2
                continue
            state = "normal"
        elif state == "bracket" and char == "]":
            if following == "]":
                output.extend((char, following))
                index += 2
                continue
            state = "normal"
        elif state == "backtick" and char == "`":
            if following == "`":
                output.extend((char, following))
                index += 2
                continue
            state = "normal"
        elif state == "line_comment" and char in "\r\n":
            state = "normal"
        elif state == "block_comment" and char == "*" and following == "/":
            output.extend((char, following))
            index += 2
            state = "normal"
            continue
        output.append(char)
        index += 1
    return "".join(output), indexes


@dataclass(frozen=True)
class BoundQuery:
    internal_sql: str
    parameters: tuple[Any, ...]
    db_type: str
    parameter_style: ParameterStyle

    def __post_init__(self) -> None:
        _, indexes = _replace_outside_sql_literals(self.internal_sql, parameter_token)
        expected = list(range(len(self.parameters)))
        if indexes != expected:
            raise BoundQueryError("SQL parameters must be present exactly once in ordered, contiguous positions")

    @classmethod
    def from_legacy(
        cls,
        *,
        sql: str,
        parameters: list[Any],
        db_type: str,
        parameter_style: ParameterStyle,
    ) -> BoundQuery:
        if not parameters:
            return cls(sql, (), db_type, parameter_style)
        output: list[str] = []
        index = 0
        parameter_index = 0
        state = "normal"
        while index < len(sql):
            char = sql[index]
            following = sql[index + 1] if index + 1 < len(sql) else ""
            if state == "normal":
                if char == "'":
                    state = "single"
                elif char == '"':
                    state = "double"
                elif char == "[":
                    state = "bracket"
                elif char == "`":
                    state = "backtick"
                elif char == "-" and following == "-":
                    state = "line_comment"
                elif char == "/" and following == "*":
                    state = "block_comment"
                elif sql.startswith("%s", index):
                    output.append(parameter_token(parameter_index))
                    parameter_index += 1
                    index += 2
                    continue
            elif state == "single" and char == "'":
                if following == "'":
                    output.extend((char, following))
                    index += 2
                    continue
                state = "normal"
            elif state == "double" and char == '"':
                if following == '"':
                    output.extend((char, following))
                    index += 2
                    continue
                state = "normal"
            elif state == "bracket" and char == "]":
                if following == "]":
                    output.extend((char, following))
                    index += 2
                    continue
                state = "normal"
            elif state == "backtick" and char == "`":
                if following == "`":
                    output.extend((char, following))
                    index += 2
                    continue
                state = "normal"
            elif state == "line_comment" and char in "\r\n":
                state = "normal"
            elif state == "block_comment" and char == "*" and following == "/":
                output.extend((char, following))
                index += 2
                state = "normal"
                continue
            output.append(char)
            index += 1
        if parameter_index != len(parameters):
            raise BoundQueryError("SQL parameter count does not match bound values")
        return cls("".join(output), tuple(parameters), db_type, parameter_style)

    def governance_sql(self) -> tuple[str, tuple[str, ...]]:
        base = 8_100_000_000_000_000_000
        while str(base) in self.internal_sql:
            base -= 10_000
        sentinels = tuple(str(base + index) for index in range(len(self.parameters)))
        rendered, _ = _replace_outside_sql_literals(self.internal_sql, lambda index: sentinels[index])
        return rendered, sentinels

    def restore_after_governance(self, sql: str, sentinels: tuple[str, ...]) -> str:
        restored = sql
        for index, sentinel in enumerate(sentinels):
            occurrences = [match.start() for match in re.finditer(rf"\b{re.escape(sentinel)}\b", restored)]
            if len(occurrences) != 1:
                raise BoundQueryError("Governance changed the bound parameter structure")
            restored = re.sub(
                rf"\b{re.escape(sentinel)}\b",
                parameter_token(index),
                restored,
                count=1,
            )
        return restored

    def render(self, sql: str | None = None) -> RenderedBoundQuery:
        source = self.internal_sql if sql is None else sql

        def placeholder(index: int) -> str:
            if self.parameter_style == ParameterStyle.FORMAT:
                return "%s"
            if self.parameter_style == ParameterStyle.NUMERIC_DOLLAR:
                return f"${index + 1}"
            if self.parameter_style == ParameterStyle.QMARK:
                return "?"
            return f"%(sp_dashboard_{index})s"

        rendered, indexes = _replace_outside_sql_literals(source, placeholder)
        if indexes != list(range(len(self.parameters))):
            raise BoundQueryError("Rendered SQL parameter order changed")
        native_parameters: list[Any] | dict[str, Any]
        if self.parameter_style == ParameterStyle.NAMED_PYFORMAT:
            native_parameters = {f"sp_dashboard_{index}": value for index, value in enumerate(self.parameters)}
        else:
            native_parameters = list(self.parameters)
        return RenderedBoundQuery(rendered, native_parameters)
