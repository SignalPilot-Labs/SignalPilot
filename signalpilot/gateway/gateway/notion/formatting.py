"""Formatting helpers for Notion rich_text and block payloads."""

from __future__ import annotations

import re
from typing import Any

NOTION_RICH_TEXT_MAX_LENGTH = 2000
NOTION_BLOCK_CHILD_LIMIT = 100

_DEFAULT_ANNOTATIONS = {
    "bold": False,
    "italic": False,
    "strikethrough": False,
    "underline": False,
    "code": False,
    "color": "default",
}
_TOKEN_RE = re.compile(
    r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)"
    r"|`([^`\n]+)`"
    r"|\*\*([^*\n]+)\*\*"
    r"|~~([^~\n]+)~~"
    r"|(?<!\*)\*([^*\n]+)\*(?!\*)"
    r"|(?<!\w)_([^_\n]+)_(?!\w)"
    r"|(https?://[^\s<>)\]]+)"
)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_BULLET_RE = re.compile(r"^\s*[-*+•]\s+(.+)$")
_NUMBERED_RE = re.compile(r"^\s*(\d+)[.)]\s+(.+)$")
_QUOTE_RE = re.compile(r"^\s*>\s?(.+)$")
_FENCE_RE = re.compile(r"^\s*```[A-Za-z0-9_+.-]*\s*$")
_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")


def _with_annotations(overrides: dict[str, Any] | None) -> dict[str, Any] | None:
    if not overrides:
        return None
    return {**_DEFAULT_ANNOTATIONS, **overrides}


def _split_text(content: str, size: int = NOTION_RICH_TEXT_MAX_LENGTH) -> list[str]:
    return [content[index : index + size] for index in range(0, len(content), size)]


class _RichTextBuilder:
    def __init__(self, max_chars: int | None = None) -> None:
        self.parts: list[dict[str, Any]] = []
        self._remaining = max_chars

    def append(
        self,
        content: str,
        *,
        annotations: dict[str, Any] | None = None,
        link_url: str | None = None,
    ) -> None:
        if not content or self._remaining == 0:
            return
        if self._remaining is not None:
            content = content[: self._remaining]
            self._remaining -= len(content)
        for chunk in _split_text(content):
            text: dict[str, Any] = {"content": chunk}
            if link_url:
                text["link"] = {"url": link_url}
            part: dict[str, Any] = {"type": "text", "text": text}
            annotation_payload = _with_annotations(annotations)
            if annotation_payload:
                part["annotations"] = annotation_payload
            self.parts.append(part)


def plain_rich_text(content: str, *, max_chars: int | None = NOTION_RICH_TEXT_MAX_LENGTH) -> list[dict[str, Any]]:
    builder = _RichTextBuilder(max_chars=max_chars)
    builder.append(content)
    return builder.parts


def linked_rich_text(label: str, url: str) -> list[dict[str, Any]]:
    builder = _RichTextBuilder()
    builder.append(label, link_url=url)
    return builder.parts


def _append_url(builder: _RichTextBuilder, url: str, annotations: dict[str, Any] | None = None) -> None:
    trailing = ""
    while url and url[-1] in ".,;:!?":
        trailing = url[-1] + trailing
        url = url[:-1]
    if url:
        builder.append(url, annotations=annotations, link_url=url)
    if trailing:
        builder.append(trailing, annotations=annotations)


def _append_inline(
    builder: _RichTextBuilder,
    content: str,
    *,
    annotations: dict[str, Any] | None = None,
) -> None:
    position = 0
    for match in _TOKEN_RE.finditer(content):
        builder.append(content[position : match.start()], annotations=annotations)
        link_label, link_url, code_text, bold_text, strike_text, italic_star_text, italic_underscore_text, raw_url = match.groups()
        if link_label and link_url:
            builder.append(link_label, annotations=annotations, link_url=link_url)
        elif code_text is not None:
            builder.append(code_text, annotations={**(annotations or {}), "code": True})
        elif bold_text is not None:
            _append_inline(builder, bold_text, annotations={**(annotations or {}), "bold": True})
        elif strike_text is not None:
            _append_inline(builder, strike_text, annotations={**(annotations or {}), "strikethrough": True})
        elif italic_star_text is not None:
            _append_inline(builder, italic_star_text, annotations={**(annotations or {}), "italic": True})
        elif italic_underscore_text is not None:
            _append_inline(builder, italic_underscore_text, annotations={**(annotations or {}), "italic": True})
        elif raw_url:
            _append_url(builder, raw_url, annotations=annotations)
        position = match.end()
    builder.append(content[position:], annotations=annotations)


def _strip_nested_bullet_marker(content: str) -> str:
    return re.sub(r"^\s*[•*-]\s+", "", content).strip()


def inline_rich_text(
    content: str,
    *,
    max_chars: int | None = None,
    annotations: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    builder = _RichTextBuilder(max_chars=max_chars)
    _append_inline(builder, content, annotations=annotations)
    return builder.parts


def markdown_rich_text(content: str, *, max_chars: int | None = None) -> list[dict[str, Any]]:
    """Render light Markdown-ish text into Notion rich_text for comments."""
    builder = _RichTextBuilder(max_chars=max_chars)
    lines = content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    in_code = False
    emitted = False

    for line in lines:
        stripped = line.strip()
        if _FENCE_RE.match(stripped):
            in_code = not in_code
            continue
        if emitted:
            builder.append("\n")
        emitted = True

        if in_code:
            builder.append(line, annotations={"code": True})
            continue

        heading = _HEADING_RE.match(stripped)
        if heading:
            _append_inline(builder, heading.group(2), annotations={"bold": True})
            continue

        bullet = _BULLET_RE.match(line)
        if bullet:
            builder.append("• ")
            _append_inline(builder, _strip_nested_bullet_marker(bullet.group(1)))
            continue

        numbered = _NUMBERED_RE.match(line)
        if numbered:
            builder.append(f"{numbered.group(1)}. ")
            _append_inline(builder, numbered.group(2).strip())
            continue

        _append_inline(builder, line)

    return builder.parts


def paragraph_block(content: str | list[dict[str, Any]]) -> dict[str, Any]:
    rich_text = content if isinstance(content, list) else inline_rich_text(content)
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rich_text}}


def heading_block(content: str, level: int = 2) -> dict[str, Any]:
    block_type = "heading_1" if level <= 1 else "heading_2" if level == 2 else "heading_3"
    return {"object": "block", "type": block_type, block_type: {"rich_text": inline_rich_text(content)}}


def toggle_heading_block(content: str, children: list[dict[str, Any]], level: int = 2) -> dict[str, Any]:
    block_type = "heading_1" if level <= 1 else "heading_2" if level == 2 else "heading_3"
    return {
        "object": "block",
        "type": block_type,
        block_type: {
            "rich_text": inline_rich_text(content),
            "is_toggleable": True,
            "children": children[:NOTION_BLOCK_CHILD_LIMIT],
        },
    }


def bulleted_list_item_block(content: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": inline_rich_text(_strip_nested_bullet_marker(content))},
    }


def numbered_list_item_block(content: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "numbered_list_item",
        "numbered_list_item": {"rich_text": inline_rich_text(content)},
    }


def quote_block(content: str) -> dict[str, Any]:
    return {"object": "block", "type": "quote", "quote": {"rich_text": inline_rich_text(content)}}


def code_blocks(content: str) -> list[dict[str, Any]]:
    chunks = _split_text(content or " ")
    return [
        {
            "object": "block",
            "type": "code",
            "code": {
                "rich_text": plain_rich_text(chunk),
                "language": "plain text",
            },
        }
        for chunk in chunks
    ]


def _markdown_table_cells(line: str) -> list[str] | None:
    stripped = line.strip()
    if "|" not in stripped:
        return None
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    cells = [cell.strip() for cell in stripped.split("|")]
    if len(cells) < 2:
        return None
    return cells


def _is_markdown_table_separator(line: str) -> bool:
    return bool(_TABLE_SEPARATOR_RE.match(line.strip()))


def _markdown_table_at(lines: list[str], index: int) -> tuple[dict[str, Any], int] | None:
    header = _markdown_table_cells(lines[index])
    if not header or index + 1 >= len(lines) or not _is_markdown_table_separator(lines[index + 1]):
        return None

    rows: list[list[str]] = [header]
    cursor = index + 2
    while cursor < len(lines):
        cells = _markdown_table_cells(lines[cursor])
        if not cells:
            break
        rows.append(cells)
        cursor += 1

    width = max(len(row) for row in rows)
    children = []
    for row in rows:
        padded = row + [""] * (width - len(row))
        children.append(
            {
                "object": "block",
                "type": "table_row",
                "table_row": {
                    "cells": [inline_rich_text(cell) for cell in padded],
                },
            }
        )

    return (
        {
            "object": "block",
            "type": "table",
            "table": {
                "table_width": width,
                "has_column_header": True,
                "has_row_header": False,
                "children": children[:NOTION_BLOCK_CHILD_LIMIT],
            },
        },
        cursor,
    )


def markdown_blocks(content: str, *, max_blocks: int = NOTION_BLOCK_CHILD_LIMIT) -> list[dict[str, Any]]:
    """Convert light Markdown-ish text into Notion blocks."""
    blocks: list[dict[str, Any]] = []
    paragraph_lines: list[str] = []
    code_lines: list[str] = []
    in_code = False
    lines = content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    index = 0

    def append(block: dict[str, Any]) -> None:
        if len(blocks) < max_blocks:
            blocks.append(block)

    def flush_paragraph() -> None:
        if not paragraph_lines:
            return
        paragraph = "\n".join(line.strip() for line in paragraph_lines).strip()
        paragraph_lines.clear()
        if paragraph:
            append(paragraph_block(paragraph))

    def flush_code() -> None:
        if not code_lines:
            return
        for block in code_blocks("\n".join(code_lines)):
            append(block)
        code_lines.clear()

    while index < len(lines):
        raw_line = lines[index]
        line = raw_line.rstrip()
        stripped = line.strip()

        if _FENCE_RE.match(stripped):
            if in_code:
                flush_code()
                in_code = False
            else:
                flush_paragraph()
                in_code = True
            index += 1
            continue

        if in_code:
            code_lines.append(line)
            index += 1
            continue

        if not stripped:
            flush_paragraph()
            index += 1
            continue

        table = _markdown_table_at(lines, index)
        if table:
            flush_paragraph()
            table_block, next_index = table
            append(table_block)
            index = next_index
            continue

        heading = _HEADING_RE.match(stripped)
        if heading:
            flush_paragraph()
            append(heading_block(heading.group(2), level=len(heading.group(1))))
            index += 1
            continue

        bullet = _BULLET_RE.match(line)
        if bullet:
            flush_paragraph()
            append(bulleted_list_item_block(bullet.group(1).strip()))
            index += 1
            continue

        numbered = _NUMBERED_RE.match(line)
        if numbered:
            flush_paragraph()
            append(numbered_list_item_block(numbered.group(2).strip()))
            index += 1
            continue

        quote = _QUOTE_RE.match(line)
        if quote:
            flush_paragraph()
            append(quote_block(quote.group(1).strip()))
            index += 1
            continue

        paragraph_lines.append(line)
        index += 1

    if in_code:
        flush_code()
    flush_paragraph()
    return blocks[:max_blocks]


def markdown_blocks_with_toggles(content: str, *, max_blocks: int = NOTION_BLOCK_CHILD_LIMIT) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    lines = content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    index = 0

    def next_toggle_heading(start: int) -> int:
        for candidate_index in range(start, len(lines)):
            heading = _HEADING_RE.match(lines[candidate_index].strip())
            if heading and len(heading.group(1)) == 2 and re.match(
                r"^(Detailed Research|Confidence Score(?::|\b))",
                heading.group(2),
                flags=re.IGNORECASE,
            ):
                return candidate_index
        return -1

    while index < len(lines):
        heading = _HEADING_RE.match(lines[index].strip())
        is_toggle_heading = bool(
            heading
            and len(heading.group(1)) == 2
            and re.match(r"^(Detailed Research|Confidence Score(?::|\b))", heading.group(2), flags=re.IGNORECASE)
        )

        if not is_toggle_heading:
            next_index = next_toggle_heading(index + 1)
            end_index = len(lines) if next_index == -1 else next_index
            blocks.extend(markdown_blocks("\n".join(lines[index:end_index]), max_blocks=max_blocks - len(blocks)))
            index = end_index
            if len(blocks) >= max_blocks:
                return blocks[:max_blocks]
            continue

        title = heading.group(2)
        index += 1
        section_lines: list[str] = []
        while index < len(lines):
            next_heading = _HEADING_RE.match(lines[index].strip())
            if next_heading and len(next_heading.group(1)) == 2:
                break
            section_lines.append(lines[index])
            index += 1
        children = markdown_blocks("\n".join(section_lines).strip())
        blocks.append(toggle_heading_block(title, children))
        if len(blocks) >= max_blocks:
            return blocks[:max_blocks]

    return blocks[:max_blocks] if blocks else markdown_blocks(content, max_blocks=max_blocks)


def request_prompt_blocks(prompt: str, *, source_url: str | None = None) -> list[dict[str, Any]]:
    return []
