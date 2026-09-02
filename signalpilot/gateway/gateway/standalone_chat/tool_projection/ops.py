"""Projectors for dbt, shell, knowledge, artifact and JSON tools.

Formats parsed here come from ``standalone_chat/dbt_executor.py`` and
``mcp/tools/dbt_execute.py`` (dbt), ``mcp/tools/sandbox_vm.py`` (shell),
``mcp/tools/knowledge.py`` (knowledge) and the notebook-server
``standalone_chat_tools.py`` JSON replies (artifacts).
"""

from __future__ import annotations

import re
from typing import Any

from gateway.standalone_chat.tool_projection.base import ProjectedResult, build, text_result
from gateway.standalone_chat.tool_projection.limits import (
    DBT_FAILURES_MAX,
    DBT_LOG_MAX,
    JSON_MAX,
    KNOWLEDGE_DOCS_MAX,
    KNOWLEDGE_SNIPPET_MAX,
    TERMINAL_TEXT_MAX,
)
from gateway.standalone_chat.tool_projection.text import (
    clip,
    clip_tail,
    compact_json,
    first_line,
    format_count,
    summary_text,
    try_json,
)

_DBT_ELAPSED_RE = re.compile(
    r"Finished running .*? in (?:(\d+) hours? )?(?:(\d+) minutes? and )?([\d.]+) seconds",
)
_DBT_RUN_RESULTS_RE = re.compile(r"^run_results: (.*)$", re.MULTILINE)
_EXIT_CODE_RE = re.compile(r"^exit_code: (-?\d+)$", re.MULTILINE)
_BASH_EXIT_RE = re.compile(r"^Exit code (\d+)\s*\n?")
_SEARCH_HIT_RE = re.compile(r"^\s*id=(\S+) scope=(\S+) category=(\S+) title=(.*)$")
_SNIPPET_RE = re.compile(r"^\s*snippet: (.*)$")
_DOC_HEADER_RE = re.compile(r"^\[([^:\]]+):([^\]]*)\]\[([^\]]+)\]$")


def _section(text: str, name: str, *others: str) -> str:
    """Return the body of ``name:`` up to the next of ``others`` markers."""
    marker = f"{name}:"
    body: list[str] | None = None
    for line in text.split("\n"):
        if body is None:
            if line.startswith(marker):
                body = [line[len(marker) :].strip()]
            continue
        if any(line.startswith(f"{other}:") for other in others):
            break
        body.append(line)
    return "\n".join(body).strip("\n") if body else ""


def project_dbt(content: str, tool_input: dict[str, Any] | None) -> ProjectedResult:
    text = content or ""
    if text.startswith("Error"):
        return text_result(text, summary=first_line(text))
    tool_input = tool_input if isinstance(tool_input, dict) else {}
    command = str(tool_input.get("command") or ("run" if tool_input.get("mart") else "") or "").strip()
    result: dict[str, Any] = {"kind": "dbt_run", "statuses": {}, "total": 0, "failures": []}
    if command:
        result["command"] = command
    for key in ("target_schema", "sync"):
        value = _section(text, key, "target_schema", "sync", "exit_code", "output", "run_results", "failures")
        if value:
            result[key] = first_line(value)
    exit_match = _EXIT_CODE_RE.search(text)
    result["exit_code"] = int(exit_match.group(1)) if exit_match else None
    log = _section(text, "output", "run_results", "failures")
    result["log"], result["log_truncated"] = clip_tail(log, DBT_LOG_MAX)
    statuses: dict[str, int] = {}
    run_results = _DBT_RUN_RESULTS_RE.search(text)
    if run_results:
        for part in run_results.group(1).split(","):
            key, sep, value = part.strip().partition("=")
            if sep and value.isdigit():
                statuses[key] = int(value)
    result["statuses"] = statuses
    result["total"] = sum(statuses.values())
    failures_text = _section(text, "failures")
    failures = []
    for line in failures_text.splitlines()[:DBT_FAILURES_MAX]:
        node, sep, message = line.partition(": ")
        if sep:
            failures.append({"node": node.strip(), "message": message.strip()})
    result["failures"] = failures
    elapsed = _DBT_ELAPSED_RE.search(log)
    if elapsed:
        hours, minutes, seconds = elapsed.groups()
        result["elapsed_s"] = int(hours or 0) * 3600 + int(minutes or 0) * 60 + float(seconds)
    summary = _dbt_summary(command, statuses, result.get("elapsed_s"), result["exit_code"])
    return build(result, summary=summary, text=text, truncated=result["log_truncated"])


def _dbt_summary(command: str, statuses: dict[str, int], elapsed_s: float | None, exit_code: int | None) -> str:
    head = f"dbt {command}" if command else "dbt"
    parts = [head]
    if statuses:
        ordered = sorted(statuses.items(), key=lambda item: (item[0] not in ("success", "pass"), item[0]))
        parts.append(", ".join(f"{count} {status}" for status, count in ordered))
    elif exit_code is not None:
        parts.append(f"exit {exit_code}")
    if elapsed_s is not None:
        parts.append(f"{elapsed_s:.0f} s" if elapsed_s >= 10 else f"{elapsed_s:.1f} s")
    return " · ".join(parts)


def _terminal(*, command: str | None, exit_code: int | None, stdout: str, stderr: str, text: str) -> ProjectedResult:
    out, out_cut = clip(stdout, TERMINAL_TEXT_MAX)
    err, err_cut = clip(stderr, TERMINAL_TEXT_MAX)
    result: dict[str, Any] = {
        "kind": "terminal",
        "exit_code": exit_code,
        "stdout": out,
        "stderr": err,
        "stdout_truncated": out_cut,
        "stderr_truncated": err_cut,
    }
    if command:
        result["command"] = command
    line_count = len((stdout or stderr).splitlines())
    exit_label = f"exit {exit_code}" if exit_code is not None else "done"
    summary = f"{exit_label} · {line_count} line{'s' if line_count != 1 else ''}"
    return build(result, summary=summary, text=text, truncated=out_cut or err_cut)


def project_sandbox_exec(content: str, tool_input: dict[str, Any] | None) -> ProjectedResult:
    text = content or ""
    if text.startswith("Error"):
        return text_result(text, summary=first_line(text))
    exit_match = _EXIT_CODE_RE.search(text)
    command = str(tool_input.get("command") or "") if isinstance(tool_input, dict) else ""
    return _terminal(
        command=command or None,
        exit_code=int(exit_match.group(1)) if exit_match else None,
        stdout=_section(text, "stdout", "stderr"),
        stderr=_section(text, "stderr"),
        text=text,
    )


def project_bash(content: str, tool_input: dict[str, Any] | None, *, is_error: bool) -> ProjectedResult:
    text = content or ""
    command = str(tool_input.get("command") or "") if isinstance(tool_input, dict) else ""
    exit_code: int | None = 0 if not is_error else None
    body = text
    match = _BASH_EXIT_RE.match(text)
    if match:
        exit_code = int(match.group(1))
        body = text[match.end() :]
    return _terminal(
        command=command or None,
        exit_code=exit_code,
        stdout=body if not is_error else "",
        stderr=body if is_error else "",
        text=text,
    )


def project_knowledge(content: str, tool_input: dict[str, Any] | None, *, mode: str) -> ProjectedResult:
    text = content or ""
    if text.startswith("Error"):
        return text_result(text, summary=first_line(text))
    docs: list[dict[str, Any]] = []
    result: dict[str, Any] = {"kind": "knowledge", "mode": mode, "docs": docs, "total": 0, "truncated": False}
    query = None
    if isinstance(tool_input, dict):
        query = tool_input.get("query") or tool_input.get("task_description")
    if query:
        result["query"] = str(query)[:200]
    total = 0
    if mode == "search":
        for line in text.splitlines():
            if hit := _SEARCH_HIT_RE.match(line):
                total += 1
                if len(docs) < KNOWLEDGE_DOCS_MAX:
                    docs.append(
                        {
                            "id": hit.group(1),
                            "scope": hit.group(2),
                            "category": hit.group(3),
                            "title": hit.group(4).strip(),
                        }
                    )
            elif docs and (snippet := _SNIPPET_RE.match(line)):
                docs[-1].setdefault("snippet", snippet.group(1).strip("'\"")[:KNOWLEDGE_SNIPPET_MAX])
    else:
        lines = text.splitlines()
        index = 0
        while index < len(lines):
            header = _DOC_HEADER_RE.match(lines[index].strip())
            if header and index + 1 < len(lines) and lines[index + 1].startswith("## "):
                total += 1
                body: list[str] = []
                cursor = index + 2
                while cursor < len(lines) and not _DOC_HEADER_RE.match(lines[cursor].strip()):
                    body.append(lines[cursor])
                    cursor += 1
                if len(docs) < KNOWLEDGE_DOCS_MAX:
                    docs.append(
                        {
                            "scope": f"{header.group(1)}:{header.group(2)}",
                            "category": header.group(3),
                            "title": lines[index + 1][3:].strip(),
                            "snippet": "\n".join(body).strip()[:KNOWLEDGE_SNIPPET_MAX],
                        }
                    )
                index = cursor
                continue
            index += 1
    result["total"] = total
    result["truncated"] = total > len(docs)
    summary = f"{format_count(total)} doc{'s' if total != 1 else ''}"
    return build(result, summary=summary, text=text, truncated=result["truncated"])


def project_artifact(content: str, tool_input: dict[str, Any] | None, *, tool: str) -> ProjectedResult:
    text = content or ""
    parsed = try_json(text)
    if not isinstance(parsed, dict):
        return text_result(text, summary=summary_text(text, "Artifact"))
    result: dict[str, Any] = {"kind": "artifact", "published": bool(parsed.get("published"))}
    if tool.endswith("start_analysis_notebook"):
        result["artifact_kind"] = "notebook"
        for key in ("session_id", "notebook_path", "notebook", "status"):
            if parsed.get(key):
                result[key] = str(parsed[key])
        status = str(parsed.get("status") or "")
        summary = "Notebook already running" if status == "already_running" else "Notebook started"
    elif tool.endswith("create_dashboard_preview"):
        result["artifact_kind"] = "dashboard"
        if parsed.get("authoring_session_id"):
            result["dashboard_session_id"] = str(parsed["authoring_session_id"])
        if parsed.get("status"):
            result["status"] = str(parsed["status"])
        charts = parsed.get("chart_count")
        name = str(parsed.get("dashboard_name") or "Dashboard preview")
        summary = f"{name} · {charts} chart{'s' if charts != 1 else ''}" if isinstance(charts, int) else name
    else:
        return text_result(text, summary=summary_text(text, "Artifact"))
    return build(result, summary=summary, text=text)


def project_json_or_text(content: str, tool_input: dict[str, Any] | None, *, fallback: str) -> ProjectedResult:
    text = content or ""
    parsed = try_json(text)
    if parsed is None:
        return text_result(text, summary=summary_text(text, fallback))
    value = compact_json(parsed)
    if isinstance(parsed, dict):
        keys = list(parsed.keys())
        if parsed.get("error"):
            summary = f"Error · {first_line(str(parsed['error']))}"
        elif parsed.get("status"):
            summary = f"{fallback} · {parsed['status']}"
        else:
            summary = f"{fallback} · {len(keys)} field{'s' if len(keys) != 1 else ''}"
    else:
        summary = f"{fallback} · {len(parsed)} item{'s' if len(parsed) != 1 else ''}"
    projected = build({"kind": "json", "value": value}, summary=summary, text=text)
    if len(text) > JSON_MAX and projected.result_text is not None:
        projected.result_text = projected.result_text[:JSON_MAX]
    return projected
